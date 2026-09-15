"""Exercise the packaged detector on an actual macOS/Linux CI host.

Uploads go only to a loopback HTTP test receiver. Never to production.
"""
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
archive = ROOT / 'apps/web/public/download/canmypcrunai-detector.pyz'
received = []


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        received.append((self.path, self.headers.get('x-upload-secret'), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"success":true}')

    def log_message(self, *args):
        pass


raw = subprocess.check_output([sys.executable, str(archive), '--profile-only'], timeout=90)
profile = json.loads(raw)
assert profile['os']['name'] in ('macOS', 'Linux')
assert profile['memory']['totalBytes'] > 0
assert profile['cpu']['physicalCores'] > 0
assert profile['cpu']['logicalCores'] >= profile['cpu']['physicalCores']
assert profile['storage']['freeBytes'] >= 0
if profile['os']['name'] == 'macOS' and profile['os']['arch'] == 'arm64':
    assert profile['memory']['unified']
    assert profile['gpus'][0]['backends'] == ['metal']
    assert profile['gpus'][0]['vramTotalBytes'] == 0
assert 'serial' not in raw.decode().lower()
(ROOT / 'unix-hardware-profile.json').write_bytes(raw)

server = HTTPServer(('127.0.0.1', 0), Receiver)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    with tempfile.TemporaryDirectory() as tmp:
        pairing_bytes = bytes.fromhex('1234567890abcdef' + 'a' * 32)
        token = base64.urlsafe_b64encode(pairing_bytes).decode().rstrip('=')
        paired = Path(tmp) / ('CanMyPCRunAI_' + token + ' (1).pyz')
        shutil.copyfile(archive, paired)
        subprocess.run([sys.executable, str(paired), '--server', 'http://127.0.0.1:' + str(server.server_port)], check=True, timeout=90)
    assert len(received) == 1
    path, secret, body = received[0]
    assert path == '/api/scan/scan-1234567890abcdef'
    assert secret == 'a' * 32
    assert body['hardware']['os']['name'] == profile['os']['name']
finally:
    server.shutdown()
    server.server_close()
    thread.join()
print(json.dumps({'platform': profile['os'], 'cpu': profile['cpu'], 'ramBytes': profile['memory']['totalBytes'], 'upload': 'loopback passed'}))
