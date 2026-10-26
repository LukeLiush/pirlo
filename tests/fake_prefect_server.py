"""A stand-in for `prefect server start`: answers GET /api/health on loopback.

Usage: python fake_prefect_server.py PORT [STARTUP_DELAY_SECONDS]
"""

import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200 if self.path == "/api/health" else 404)
        self.end_headers()
        self.wfile.write(b"true")

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1])
    time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 0)
    print(f"fake prefect server on 127.0.0.1:{port}", flush=True)
    HTTPServer(("127.0.0.1", port), _Health).serve_forever()
