"""D2: a client that hangs up before reading its answer must not get a second (500) response written."""
import unittest

import server


class GoneClient:
    def __init__(self):
        self.writes = 0

    def write(self, data):
        self.writes += 1
        raise BrokenPipeError(32, "Broken pipe")


class BrokenPipeTests(unittest.TestCase):
    def handler(self):
        h = server.Handler.__new__(server.Handler)  # no socket: only the response path is exercised
        h.wfile = GoneClient()
        h.headers_sent = []
        h.send_response = lambda status: h.headers_sent.append(status)
        h.send_header = lambda *a: None
        h.end_headers = lambda: None
        h.close_connection = False
        return h

    def test_disconnect_is_absorbed_and_nothing_is_written_twice(self):
        h = self.handler()
        h._send(200, {"ok": True})  # raised BrokenPipeError before the fix
        self.assertTrue(h.close_connection)
        h._send(500, {"error": "internal_error"})  # what the old except-branch did next
        self.assertEqual((h.wfile.writes, h.headers_sent), (1, [200]))

    def test_reset_connection_is_handled_the_same_way(self):
        h = self.handler()
        h.wfile.write = lambda data: (_ for _ in ()).throw(ConnectionResetError(104, "reset"))
        h._send(200, {"ok": True})
        h._send(500, {"error": "internal_error"})
        self.assertEqual(h.headers_sent, [200])


if __name__ == "__main__":
    unittest.main()
