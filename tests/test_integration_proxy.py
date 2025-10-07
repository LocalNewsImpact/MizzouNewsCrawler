import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
import time
from urllib.parse import parse_qs, urlparse

from src.crawler.origin_proxy import enable_origin_proxy, disable_origin_proxy


class EchoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        # Respond with the proxied url and auth header presence
        auth = self.headers.get('Authorization')
        body = f"path={parsed.path}&q={qs.get('url')}&auth={bool(auth)}"
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body.encode('utf-8'))

    def log_message(self, format, *args):
        return


def run_server(server):
    server.serve_forever()


def test_integration_origin_proxy(monkeypatch):
    server = HTTPServer(('127.0.0.1', 0), EchoHandler)
    port = server.server_address[1]
    t = threading.Thread(target=run_server, args=(server,), daemon=True)
    t.start()

    s = requests.Session()
    # fake the original request to go to the http server
    monkeypatch.setenv('USE_ORIGIN_PROXY', '1')
    monkeypatch.setenv('ORIGIN_PROXY_URL', f'http://127.0.0.1:{port}')
    monkeypatch.setenv('PROXY_USERNAME', 'u')
    monkeypatch.setenv('PROXY_PASSWORD', 'p')

    enable_origin_proxy(s)

    r = s.get('https://example.com/somepath')
    assert r.status_code == 200
    text = r.text
    # ensure proxied URL and auth indicator present
    assert 'example.com/somepath' in text
    assert 'auth=True' in text

    disable_origin_proxy(s)
    server.shutdown()
    time.sleep(0.05)
