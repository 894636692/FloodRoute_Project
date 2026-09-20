"""Local-only sink for browser diagnostic exports; never part of the demo."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATIONS = {
    '/probe': ROOT / 'scripts/ui_browser_probe.js',
    '/before': ROOT / 'work/ui_e2e_before.json',
    '/after': ROOT / 'work/ui_e2e_after.json',
    '/cold_before': ROOT / 'work/ui_e2e_cold_before.json',
    '/cold_after': ROOT / 'work/ui_e2e_cold_after.json',
    '/tiles': ROOT / 'work/ui_e2e_tiles.json',
}

class Capture(BaseHTTPRequestHandler):
    def headers_ok(self):
        origin = self.headers.get('Origin')
        if origin in ('http://127.0.0.1:8502', 'http://127.0.0.1:8504'):
            self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    def do_OPTIONS(self):
        self.send_response(204); self.headers_ok(); self.end_headers()
    def do_POST(self):
        if self.path not in DESTINATIONS:
            self.send_error(404); return
        data = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        DESTINATIONS[self.path].write_bytes(data)
        self.send_response(200)
        # Both the normal and diagnostic local demo may export.
        self.headers_ok()
        self.end_headers(); self.wfile.write(b'OK')

if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8766), Capture).serve_forever()
