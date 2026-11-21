"""Shared fixtures. Everything here is offline: the only HTTP is a local server."""

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

# urllib picks up proxies from the environment and caches them in its default
# opener; make sure requests to the local test server never go through one.
for _var in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_var, None)
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"


@pytest.fixture(autouse=True)
def fake_home(tmp_path, monkeypatch):
    """Point HOME at a temp dir so nothing can touch the real ~/.local/bin etc."""
    home = tmp_path / "user-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        self.server.requests.append(self.path)
        route = self.server.routes.get(self.path)
        if route is None:
            self.send_error(404)
            return
        body, ctype = route
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class LocalServer:
    """Serves in-memory files: server.add("/x.jar", b"...") -> server.url("/x.jar")."""

    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.routes = {}
        self.httpd.requests = []
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )

    @property
    def requests(self):
        return self.httpd.requests

    def add(self, path, body, ctype="application/octet-stream"):
        if isinstance(body, str):
            body = body.encode()
        self.httpd.routes[path] = (body, ctype)
        return self.url(path)

    def url(self, path):
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}{path}"


@pytest.fixture
def http_server():
    server = LocalServer()
    server.thread.start()
    try:
        yield server
    finally:
        server.httpd.shutdown()
        server.httpd.server_close()
