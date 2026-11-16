"""Bounded-worker HTTP API for the existing Mini DBMS executor."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
from .executor import Database, IdempotencyConflict
from .parser import SQLParseError
from .storage import StorageError

MAX_BODY_BYTES = 64 * 1024

class BoundedSQLHTTPServer(HTTPServer):
    # Pending-connection backlog for listen(). socketserver's default is 5: a burst of more
    # simultaneous connects than that was reset by the OS before accept() could answer it
    # (ConnectionResetError in clients). Excess work is still limited by the worker slots
    # below and answered with HTTP 503 server_busy instead of a reset.
    request_queue_size=128
    def __init__(self, address, database, workers=4, queue_size=32):
        if workers < 1 or queue_size < 0: raise ValueError("workers must be >= 1 and queue_size >= 0")
        self.database=database; self.workers=workers; self.queue_size=queue_size
        self.pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix="mini-dbms")
        self.slots=threading.BoundedSemaphore(workers+queue_size); self._closed=False
        super().__init__(address,SQLRequestHandler)
    def process_request(self,request,client_address):
        if not self.slots.acquire(blocking=False):
            self._drain_request_body(request)
            payload=json.dumps({"error":"server_busy","message":"SQL worker queue is full"}).encode("utf-8")
            try: request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "+str(len(payload)).encode()+b"\r\n\r\n"+payload)
            finally: self.shutdown_request(request)
            return
        try:
            future=self.pool.submit(self._serve_one,request,client_address)
            future.add_done_callback(lambda _: self.slots.release())
        except BaseException:
            self.slots.release(); self.shutdown_request(request); raise
    def _drain_request_body(self,request):
        # Drain a bounded request so closing a saturated connection does not reset the client.
        request.settimeout(0.5); data=bytearray()
        try:
            while b"\r\n\r\n" not in data and len(data)<16*1024:
                chunk=request.recv(4096)
                if not chunk: return
                data.extend(chunk)
            header_end=data.find(b"\r\n\r\n")
            if header_end<0: return
            headers=data[:header_end].decode("latin-1").split("\r\n")[1:]
            length=next((int(line.split(":",1)[1].strip()) for line in headers if line.lower().startswith("content-length:")),0)
            remaining=max(0,min(length,MAX_BODY_BYTES+1)-(len(data)-header_end-4))
            while remaining>0:
                chunk=request.recv(min(4096,remaining))
                if not chunk: break
                remaining-=len(chunk)
        except (OSError,ValueError): pass
    def _serve_one(self,request,client_address):
        try: self.finish_request(request,client_address)
        except Exception: self.handle_error(request,client_address)
        finally: self.shutdown_request(request)
    def server_close(self):
        if not self._closed:
            self._closed=True
            super().server_close()
            self.pool.shutdown(wait=True,cancel_futures=False)

class SQLRequestHandler(BaseHTTPRequestHandler):
    server_version="MiniDBMS/1.0"
    def do_POST(self):
        if self.path not in ("/sql","/sql/insert-once"):
            return self._send(404,{"error":"not_found","message":"Use POST /sql or POST /sql/insert-once"})
        length=self.headers.get("Content-Length")
        if length is None: return self._send(411,{"error":"length_required","message":"Content-Length is required"})
        try: size=int(length)
        except ValueError: return self._send(400,{"error":"bad_request","message":"Invalid Content-Length"})
        if size<0 or size>MAX_BODY_BYTES: return self._send(413,{"error":"payload_too_large","message":f"Request body limit is {MAX_BODY_BYTES} bytes"})
        try:
            body=self.rfile.read(size); payload=json.loads(body.decode("utf-8"))
            allowed={"sql","params"} if self.path=="/sql" else {"sql","params","keyColumn"}
            if not isinstance(payload,dict) or set(payload)-allowed: raise ValueError("invalid request fields")
            sql=payload.get("sql"); params=payload.get("params",[])
            if not isinstance(sql,str) or not isinstance(params,list): raise ValueError("sql must be text and params must be a JSON array")
            if self.path=="/sql/insert-once":
                key_column=payload.get("keyColumn")
                if not isinstance(key_column,str): raise ValueError("keyColumn must be a column name")
                result=self.server.database.execute_insert_once(sql,params,key_column)
            else:
                result=self.server.database.execute(sql,params)
            return self._send(200,{"ok":True,"result":result})
        except IdempotencyConflict as exc:
            return self._send(409,{"error":"idempotency_conflict","message":str(exc)})
        except (UnicodeDecodeError,json.JSONDecodeError,ValueError,SQLParseError) as exc:
            return self._send(400,{"error":"invalid_sql_request","message":str(exc)})
        except StorageError as exc:
            return self._send(503,{"error":"storage_unavailable","message":str(exc)})
        except Exception:
            return self._send(500,{"error":"internal_error","message":"SQL execution failed"})
    def do_GET(self): self._send(405,{"error":"method_not_allowed","message":"Use POST /sql"})
    def log_message(self,format,*args): pass
    def _send(self,status,payload):
        raw=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(raw))); self.send_header("Connection","close"); self.end_headers(); self.wfile.write(raw)

def serve(data_dir,host="127.0.0.1",port=8765,workers=4,queue_size=32):
    # Constructing Database validates files and rebuilds all B+Trees before bind/listen.
    database=Database(data_dir)
    server=BoundedSQLHTTPServer((host,port),database,workers,queue_size)
    try: server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt: pass
    finally: server.shutdown(); server.server_close()

def main(argv=None):
    parser=argparse.ArgumentParser(description="Mini DBMS bounded Thread Pool SQL API")
    parser.add_argument("--data-dir",default="data"); parser.add_argument("--host",default="127.0.0.1"); parser.add_argument("--port",type=int,default=8765); parser.add_argument("--workers",type=int,default=4); parser.add_argument("--queue-size",type=int,default=32)
    args=parser.parse_args(argv); serve(args.data_dir,args.host,args.port,args.workers,args.queue_size)

if __name__=="__main__": main()
