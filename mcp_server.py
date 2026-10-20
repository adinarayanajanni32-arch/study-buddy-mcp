"""Study Buddy MCP server: Model Context Protocol, Streamable HTTP transport, spec 2025-11-25.
Endpoint: POST /mcp (JSON-RPC 2.0). Also serves the simulated Alexa+ web app at /.
Run: python mcp_server.py   (binds 127.0.0.1:8765; set PORT / HOST to change)
"""
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import core

SUPPORTED = ["2025-11-25", "2025-06-18", "2025-03-26"]
SERVER_INFO = {"name": "study-buddy", "title": "Study Buddy", "version": "1.0.0"}
S = lambda desc, **props: {"type": "object", "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
                          "required": list(props), "additionalProperties": False}

TOOLS = {
    "explain_topic": ("Explain a study topic in 2-3 short spoken sentences (uses Amazon Bedrock when configured).",
                      S("", topic="Topic or question to explain"), lambda u, a: core.explain_topic(u, a["topic"])),
    "add_task": ("Add a task to the student's study list.", S("", task="Task description"), lambda u, a: core.add_task(u, a["task"])),
    "list_tasks": ("Read back the student's study tasks.", S(""), lambda u, a: core.list_tasks(u)),
    "complete_task": ("Mark a study task as done.", S("", task="Task name or part of it"), lambda u, a: core.complete_task(u, a["task"])),
    "set_exam": ("Save an exam date.", S("", subject="Subject, e.g. physics", date="Exam date as YYYY-MM-DD"),
                 lambda u, a: core.set_exam(u, a["subject"], a["date"])),
    "next_exam": ("Tell the student how many days until the next exam.", S(""), lambda u, a: core.next_exam(u)),
    "start_quiz": ("Start a 3-question spoken quiz. Subjects: biology, physics, computer science, maths.",
                   S("", subject="Quiz subject"), lambda u, a: core.start_quiz(u, a["subject"])),
    "answer_quiz": ("Submit the student's answer to the current quiz question.", S("", answer="The student's spoken answer"),
                    lambda u, a: core.answer_quiz(u, a["answer"])),
}

def rpc_result(i, result): return {"jsonrpc": "2.0", "id": i, "result": result}
def rpc_error(i, code, msg): return {"jsonrpc": "2.0", "id": i, "error": {"code": code, "message": msg}}

def handle(msg, uid):
    """Return a JSON-RPC response dict, or None for notifications/responses."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return rpc_error(None, -32600, "Invalid Request")
    method, i, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method is None or i is None:      # notification or client response
        return None
    if method == "initialize":
        v = params.get("protocolVersion")
        return rpc_result(i, {"protocolVersion": v if v in SUPPORTED else SUPPORTED[0],
                              "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
                              "instructions": "Study assistant: explain topics, manage tasks and exams, run quizzes."})
    if method == "ping":
        return rpc_result(i, {})
    if method == "tools/list":
        return rpc_result(i, {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s, _) in TOOLS.items()]})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            return rpc_error(i, -32602, "Unknown tool: %s" % name)
        _, schema, fn = TOOLS[name]
        missing = [k for k in schema["required"] if not isinstance(args.get(k), str) or not args[k].strip()]
        if missing:
            return rpc_result(i, {"content": [{"type": "text", "text": "Missing argument(s): " + ", ".join(missing)}], "isError": True})
        try:
            return rpc_result(i, {"content": [{"type": "text", "text": fn(uid, args)}], "isError": False})
        except Exception as e:
            return rpc_result(i, {"content": [{"type": "text", "text": "Tool failed: %s" % e}], "isError": True})
    return rpc_error(i, -32601, "Method not found: %s" % method)

ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]"} | set(filter(None, os.environ.get("ALLOWED_ORIGINS", "").split(",")))

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)

    def _origin_ok(self):
        o = self.headers.get("Origin")           # DNS-rebinding protection required by the spec
        return not o or (urlparse(o).hostname or "") in {h.strip("[]") for h in ALLOWED_HOSTS} or o in ALLOWED_HOSTS

    def do_POST(self):
        if urlparse(self.path).path != "/mcp": return self._send(404)
        if not self._origin_ok(): return self._send(403, b'{"error":"bad origin"}')
        try:
            msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"null")
        except ValueError:
            return self._send(400, json.dumps(rpc_error(None, -32700, "Parse error")).encode())
        uid = self.headers.get("X-User-Id", "default")
        batch = isinstance(msg, list)
        out = [r for r in (handle(m, uid) for m in (msg if batch else [msg])) if r]
        if not out: return self._send(202)       # only notifications/responses
        extra = {}
        if not batch and msg.get("method") == "initialize":
            extra["Mcp-Session-Id"] = os.urandom(8).hex()
        self._send(200, json.dumps(out if batch else out[0]).encode(), extra=extra)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/mcp": return self._send(405, b"", extra={"Allow": "POST"})   # no server-initiated stream
        if p in ("/", "/index.html"):
            return self._send(200, open(os.path.join(os.path.dirname(__file__), "web", "index.html"), "rb").read(), "text/html; charset=utf-8")
        self._send(404)

    def do_DELETE(self): self._send(405)
    def log_message(self, *a): pass

def make_server(host="127.0.0.1", port=8765): return ThreadingHTTPServer((host, port), Handler)

if __name__ == "__main__":
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", 8765))
    print("Study Buddy MCP server: http://%s:%d/mcp  (web simulator: http://%s:%d/)" % (host, port, host, port))
    make_server(host, port).serve_forever()
