"""A tiny web service used by the demo. It writes its PID so the demo can 'crash' it."""

import http.server
import os
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
PIDFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_app.pid")


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "healthy"}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    with open(PIDFILE, "w") as fh:
        fh.write(str(os.getpid()))
    http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
