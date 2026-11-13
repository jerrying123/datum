"""Authenticated read-only local worker health API.

Only endpoint discovery is stored in the spool; liveness is checked directly.
"""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time


class WorkerHealth:
    def __init__(self, root, status):
        self.root = Path(root)
        self.token = secrets.token_hex(32)
        self.status = status
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                valid = hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + parent.token)
                if self.path != '/health' or not valid:
                    self.send_error(404)
                    return
                payload = parent.status()
                body = json.dumps(payload, allow_nan=False).encode()
                self.send_response(200 if payload.get('available') else 503)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer((os.environ.get('DATUM_WORKER_HEALTH_BIND', '0.0.0.0'), 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.endpoint = self.root / ('worker-endpoint-%020d.json' % time.time_ns())
        try:
            for old in self.root.glob('worker-endpoint-*.json'):
                old.unlink(missing_ok=True)
            # The private token and ephemeral port are immutable after publication.
            fd = os.open(self.endpoint, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as out:
                json.dump({'port': self.server.server_port, 'token': self.token}, out)
            self.thread.start()
        except BaseException:
            self.endpoint.unlink(missing_ok=True)
            self.server.server_close()
            raise

    def close(self):
        self.endpoint.unlink(missing_ok=True)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
