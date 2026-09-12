"""The download session's retry layer, exercised against real sockets.

The step 3 tests use a scripted fake session, which never reaches urllib3.
These cover what only the real adapter can get wrong: retrying underneath
_download_pdf, and turning a read timeout into something its `except Timeout`
clause cannot see.
"""
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests

from scraper.session import _DEFAULT_FORCELIST, _retry_adapter, build_download_session


@pytest.fixture
def busy_host():
    """Answers every request 429, and counts them."""
    hits = []

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            body = b"busy"
            self.send_response(429)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", hits
    server.shutdown()
    server.server_close()


@pytest.fixture
def silent_host():
    """Accepts connections and never answers, and counts them."""
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    accepted = []

    def _accept():
        while True:
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            accepted.append(connection)

    threading.Thread(target=_accept, daemon=True).start()
    yield f"http://127.0.0.1:{listener.getsockname()[1]}", accepted
    listener.close()
    for connection in accepted:
        connection.close()


def test_a_429_is_handed_straight_back_to_the_caller(busy_host):
    # _download_pdf owns the 429 schedule, including halving concurrency. An
    # adapter retry here would spend four requests the throttle never sees.
    base, hits = busy_host
    session = build_download_session()

    response = session.get(f"{base}/x.pdf", timeout=5, stream=True)
    response.close()

    assert response.status_code == 429
    assert len(hits) == 1


def test_a_read_timeout_reaches_the_caller_as_a_timeout(silent_host):
    # With a read budget urllib3 raises MaxRetryError instead, which requests
    # reports as ConnectionError, and one attempt costs two full timeouts.
    base, accepted = silent_host
    session = build_download_session()

    with pytest.raises(requests.exceptions.Timeout):
        session.get(f"{base}/x.pdf", timeout=1, stream=True)

    assert len(accepted) == 1


def test_steps_1_and_2_keep_the_shared_forcelist():
    assert _retry_adapter().max_retries.status_forcelist == _DEFAULT_FORCELIST
