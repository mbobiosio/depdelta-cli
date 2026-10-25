# tests/test_web.py

import io
import json
import urllib.error

import pytest

from depdelta_cli import web


class FakeReply:
    def __init__(self, status: int, raw: bytes, headers: dict | None = None):
        self.status = status
        self.raw = raw
        self.headers = headers or {}

    def read(self) -> bytes:
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    """Requests made; answer with ``sent.reply`` (a reply or an exception)."""

    class Sent(list):
        reply: object = FakeReply(200, b'{"ok": true}', {"X-A": "1"})

    calls = Sent()

    def urlopen(req, timeout):
        calls.append((req, timeout))
        if isinstance(calls.reply, BaseException):
            raise calls.reply
        return calls.reply

    monkeypatch.setattr(web.urllib.request, "urlopen", urlopen)
    return calls


def test_request_success(sent):
    reply = web.request("POST", "https://x.test/a", body={"a": 1}, headers={"B": "2"})

    assert (reply.status, reply.body, reply.headers) == (
        200,
        {"ok": True},
        {"X-A": "1"},
    )
    req, timeout = sent[0]
    assert timeout == web.TIMEOUT_SECONDS
    assert req.get_method() == "POST"
    assert json.loads(req.data) == {"a": 1}
    assert req.get_header("Content-type") == "application/json"
    assert req.get_header("B") == "2"
    assert req.get_header("User-agent") == web.USER_AGENT


def test_request_without_body(sent):
    web.request("GET", "https://x.test/a")

    req, _ = sent[0]
    assert req.data is None
    assert req.get_header("Content-type") is None


def test_request_http_error_comes_back(sent):
    sent.reply = urllib.error.HTTPError(
        "https://x.test",
        401,
        "no",
        {"Retry-After": "5"},
        io.BytesIO(b"denied"),  # type: ignore[arg-type]
    )

    reply = web.request("GET", "https://x.test/a")

    assert (reply.status, reply.body, reply.headers) == (
        401,
        "denied",
        {"Retry-After": "5"},
    )


def test_request_network_failure(sent):
    sent.reply = urllib.error.URLError("refused")

    with pytest.raises(web.HttpError, match="GET https://x.test/a"):
        web.request("GET", "https://x.test/a")


@pytest.mark.parametrize(
    ("raw", "body"),
    [
        (b')]}\'\n{"a": 1}', {"a": 1}),
        (b"", None),
        (b"plain", "plain"),
    ],
)
def test_decode(raw, body):
    assert web._decode(raw) == body


def test_basic():
    assert web.basic("bot", "pw") == "Basic Ym90OnB3"
