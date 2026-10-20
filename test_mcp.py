import unittest, json, threading, os, tempfile, urllib.request, datetime
os.environ["DATA_FILE"] = os.path.join(tempfile.mkdtemp(), "d.json")
import core, mcp_server
core.DATA_FILE = os.environ["DATA_FILE"]

def post(url, body, headers=None):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})
    try:
        r = urllib.request.urlopen(req); raw = r.read(); return r.status, (json.loads(raw) if raw else None), r.headers
    except urllib.error.HTTPError as e:
        return e.code, None, e.headers

class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = mcp_server.make_server("127.0.0.1", 0); cls.url = "http://127.0.0.1:%d/mcp" % cls.srv.server_port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def call(self, name, **a):
        s, j, _ = post(self.url, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": a}})
        self.assertEqual(s, 200); return j["result"]["content"][0]["text"]
    def test_initialize_and_list(self):
        s, j, h = post(self.url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}})
        self.assertEqual(j["result"]["protocolVersion"], "2025-11-25"); self.assertTrue(h["Mcp-Session-Id"])
        s, j, _ = post(self.url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(len(j["result"]["tools"]), 8)
    def test_notification_202(self):
        s, j, _ = post(self.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}); self.assertEqual(s, 202)
    def test_unknown_method_and_tool(self):
        _, j, _ = post(self.url, {"jsonrpc": "2.0", "id": 3, "method": "nope"}); self.assertEqual(j["error"]["code"], -32601)
        _, j, _ = post(self.url, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "x"}}); self.assertEqual(j["error"]["code"], -32602)
    def test_bad_origin_rejected(self):
        s, _, _ = post(self.url, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"Origin": "http://evil.example"}); self.assertEqual(s, 403)
    def test_tasks(self):
        h = {"X-User-Id": "t1"}
        self.assertIn("Added", self.call("add_task", task="read ch 2"))
        self.assertIn("read ch 2", self.call("list_tasks"))
        self.assertIn("done", self.call("complete_task", task="ch 2"))
    def test_exam(self):
        d = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
        self.call("set_exam", subject="maths", date=d)
        self.assertIn("5 days", self.call("next_exam"))
        self.assertIn("YYYY-MM-DD", self.call("set_exam", subject="x", date="soon"))
    def test_quiz(self):
        self.assertIn("Question 1", self.call("start_quiz", subject="biology"))
        self.assertIn("Correct", self.call("answer_quiz", answer="mitochondria"))
        self.call("answer_quiz", answer="dna"); r = self.call("answer_quiz", answer="carbon dioxide")
        self.assertIn("3 out of 3", r)
    def test_missing_arg(self):
        _, j, _ = post(self.url, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "add_task", "arguments": {}}})
        self.assertTrue(j["result"]["isError"])
    def test_web_page_and_get(self):
        self.assertIn(b"Study Buddy", urllib.request.urlopen(self.url[:-4]).read())
        with self.assertRaises(urllib.error.HTTPError) as c: urllib.request.urlopen(self.url)
        self.assertEqual(c.exception.code, 405)

if __name__ == "__main__": unittest.main()
