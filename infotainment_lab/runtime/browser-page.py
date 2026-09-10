"""Serve only the bundled browser check page on a private loopback port."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import signal
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import atomic_json


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split('?', 1)[0] not in ('/', '/welcome.html'):
            self.send_error(404)
            return
        content = Path(__file__).with_name('welcome.html').read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    state = Path(os.environ['TESLA_NATIVE_STATE'])
    server = ThreadingHTTPServer(('127.0.0.1', 0), Page)
    server.timeout = .5
    running = True
    def stop(*_):
        global running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    atomic_json(state / 'browser-page.json', {'url': f'http://127.0.0.1:{server.server_port}/', 'phase': 'running', 'updated_at': time.time()})
    try:
        while running: server.handle_request()
    finally:
        server.server_close()
        atomic_json(state / 'browser-page.json', {'phase': 'stopped', 'updated_at': time.time()})
