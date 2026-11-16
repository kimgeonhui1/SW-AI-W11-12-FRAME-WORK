import concurrent.futures
import http.client
import json
import tempfile
import threading
import time
import unittest
from mini_dbms import Database
from mini_dbms.server import BoundedSQLHTTPServer

class BlockingDatabase:
    def __init__(self): self.entered=threading.Event(); self.release=threading.Event(); self.db=Database(tempfile.mkdtemp())
    def execute(self,sql,params=()):
        if sql=="BLOCK": self.entered.set(); self.release.wait(3); return {"rows":[]}
        return self.db.execute(sql,params)

class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=Database(self.tmp.name)
        self.server=BoundedSQLHTTPServer(("127.0.0.1",0),self.db,workers=4,queue_size=256)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
    def tearDown(self): self.server.shutdown(); self.server.server_close(); self.thread.join(2); self.tmp.cleanup()
    def request(self,payload,path="/sql"):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=5)
        body=json.dumps(payload); conn.request("POST",path,body,{"Content-Type":"application/json"}); res=conn.getresponse(); data=json.loads(res.read()); conn.close(); return res.status,data
    def test_queue_saturation_returns_503(self):
        entered=threading.Event(); release=threading.Event()
        class Gate:
            def execute(self,sql,params=()): entered.set(); release.wait(2); return {"rows":[]}
        server=BoundedSQLHTTPServer(("127.0.0.1",0),Gate(),workers=1,queue_size=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        first=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            pending=first.submit(lambda: self._request_to(server.server_port,{"sql":"SELECT * FROM players"}))
            self.assertTrue(entered.wait(2))
            status,data=self._request_to(server.server_port,{"sql":"SELECT * FROM players"})
            self.assertEqual(status,503); self.assertEqual(data["error"],"server_busy")
            release.set(); self.assertEqual(pending.result(timeout=3)[0],200)
        finally:
            release.set(); server.shutdown(); server.server_close(); thread.join(2); first.shutdown(wait=True)
    @staticmethod
    def _request_to(port,payload):
        conn=http.client.HTTPConnection("127.0.0.1",port,timeout=4); conn.request("POST","/sql",json.dumps(payload),{"Content-Type":"application/json"}); response=conn.getresponse(); result=json.loads(response.read()); conn.close(); return response.status,result
    def test_insert_select_and_bad_requests(self):
        self.assertEqual(self.request({"sql":"INSERT INTO players (display_name, created_at) VALUES (?, ?)","params":["A","today"]})[0],200)
        status,data=self.request({"sql":"SELECT * FROM players WHERE id = ?","params":[1]}); self.assertEqual(status,200); self.assertEqual(data["result"]["rows"][0]["display_name"],"A")
        self.assertEqual(self.request({"sql":"DROP TABLE x"})[0],400)
        self.assertEqual(self.request({"sql":7})[0],400)
        self.assertEqual(self.request({},"/bad")[0],404)
    def test_parallel_select_insert_id_and_integrity(self):
        sql="INSERT INTO players (display_name, created_at) VALUES (?, ?)"
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as clients:
            futures=[clients.submit(self.request,{"sql":sql,"params":[f"p{i}","today"]}) for i in range(200)]
            responses=[f.result() for f in futures]
        self.assertTrue(all(status==200 for status,_ in responses))
        ids=sorted(data["result"]["insertedId"] for _,data in responses)
        self.assertEqual(ids,list(range(1,201)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as clients:
            reads=list(clients.map(lambda _: self.request({"sql":"SELECT * FROM players"}),range(50)))
        self.assertTrue(all(s==200 and len(d["result"]["rows"])==200 for s,d in reads))
        table=self.db.tables["players"]
        self.assertEqual(table.index.size,200)
        self.assertEqual(list(table.index.items()),[(row["id"],offset) for row,offset in table.rows])
    def test_connection_burst_is_accepted_not_reset(self):
        # Regression: with listen backlog 5, simultaneous connects beyond the backlog were reset.
        self.assertGreaterEqual(BoundedSQLHTTPServer.request_queue_size,128)
        start=threading.Barrier(48)
        def burst(_):
            start.wait(5); return self.request({"sql":"SELECT * FROM players"})
        for _ in range(3):
            with concurrent.futures.ThreadPoolExecutor(max_workers=48) as clients:
                statuses=[status for status,_ in clients.map(burst,range(48))]
            self.assertEqual(statuses,[200]*48)
    def test_insert_once_api_is_atomic_for_concurrent_retries(self):
        sql="INSERT INTO guest_users (user_id, token_hash, display_name, created_at) VALUES (?, ?, ?, ?)"
        body={"sql":sql,"params":["guest-a","hash-a","Ada","today"],"keyColumn":"token_hash"}
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as clients:
            responses=list(clients.map(lambda _: self.request(body,"/sql/insert-once"),range(24)))
        self.assertTrue(all(status==200 for status,_ in responses))
        ids={data["result"]["insertedId"] for _,data in responses}
        self.assertEqual(ids,{1})
        self.assertEqual(sum(data["result"]["created"] for _,data in responses),1)
        self.assertEqual(len(self.db.tables["guest_users"].rows),1)
        conflict={**body,"params":["guest-b","hash-a","Grace","today"]}
        self.assertEqual(self.request(conflict,"/sql/insert-once")[0],409)
    def test_mixed_reads_writes_and_restart(self):
        sql="INSERT INTO players (display_name, created_at) VALUES (?, ?)"
        def op(i):
            if i%3==0: return self.request({"sql":"SELECT id FROM players"})
            return self.request({"sql":sql,"params":[f"m{i}","today"]})
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as clients: outcomes=list(clients.map(op,range(120)))
        self.assertTrue(all(status==200 for status,_ in outcomes))
        expected=len([i for i in range(120) if i%3])
        self.assertEqual(len(self.db.execute("SELECT * FROM players")["rows"]),expected)
        recovered=Database(self.tmp.name); self.assertEqual(recovered.tables["players"].index.size,expected)
        self.assertEqual(len(recovered.execute("SELECT * FROM players")["rows"]),expected)

if __name__=="__main__": unittest.main()
