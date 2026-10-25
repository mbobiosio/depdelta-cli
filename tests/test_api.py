# tests/test_api.py

import pytest
from helpers import FakeWeb, ok, review, update

from depdelta_cli import api as module
from depdelta_cli import web
from depdelta_cli.api import ApiError, DepDelta, Review, _message
from depdelta_cli.git import ChangedFile

FILES = [ChangedFile("package.json", '{"a": 1}', '{"a": 2}')]


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock():
    return Clock()


def client(clock: Clock) -> DepDelta:
    return DepDelta(
        "dd_key", "https://api.test/api/v1/", sleep=clock.sleep, clock=clock
    )


def test_ask_success(monkeypatch, clock):
    fake = FakeWeb(review(updates=[update()]))
    monkeypatch.setattr(web, "request", fake)

    got = client(clock).ask(
        FILES, usage=[{"x": 1}], fmt="text", source_url="https://g.test/-/blob/s"
    )

    assert got == Review(
        status="ready",
        label="🔴 Breaking",
        body="### DepDelta review",
        retry_after=None,
        verdict="breaking",
        updates=[update()],
    )
    call = fake.calls[0]
    assert (call["method"], call["url"]) == (
        "POST",
        "https://api.test/api/v1/ci/reviews",
    )
    assert call["body"] == {
        "files": [{"path": "package.json", "base": '{"a": 1}', "head": '{"a": 2}'}],
        "usage": [{"x": 1}],
        "format": "text",
        "source_url": "https://g.test/-/blob/s",
    }
    assert call["headers"]["Authorization"] == "Bearer dd_key"
    assert len(call["headers"]["Idempotency-Key"]) == 36


def test_ask_defaults(monkeypatch, clock):
    fake = FakeWeb(ok({"data": {"status": "ready", "label": "x", "body": "b"}}))
    monkeypatch.setattr(web, "request", fake)

    got = client(clock).ask(FILES)

    assert (got.updates, got.retry_after, got.verdict) == ([], None, None)
    assert fake.calls[0]["body"]["format"] == "markdown"
    assert "source_url" not in fake.calls[0]["body"]


def test_ask_retries_server_errors(monkeypatch, clock):
    fake = FakeWeb(ok(None, 502), web.HttpError("down"), review())
    monkeypatch.setattr(web, "request", fake)

    assert client(clock).ask(FILES).status == "ready"
    assert clock.slept == [module.RETRY_SECONDS, module.RETRY_SECONDS * 2]
    keys = {c["headers"]["Idempotency-Key"] for c in fake.calls}
    assert len(keys) == 3


def test_ask_server_error_after_every_attempt(monkeypatch, clock):
    monkeypatch.setattr(web, "request", FakeWeb(*[ok("Bad gateway", 502)] * 3))

    with pytest.raises(ApiError, match="DepDelta answered 502: Bad gateway"):
        client(clock).ask(FILES)


def test_ask_network_failure_after_every_attempt(monkeypatch, clock):
    monkeypatch.setattr(web, "request", FakeWeb(*[web.HttpError("refused")] * 3))

    with pytest.raises(ApiError, match="refused"):
        client(clock).ask(FILES)


def test_ask_refused(monkeypatch, clock):
    body = {"detail": {"message": "Send a DepDelta API key", "error": True}}
    monkeypatch.setattr(web, "request", FakeWeb(ok(body, 401)))

    with pytest.raises(ApiError, match="401: Send a DepDelta API key"):
        client(clock).ask(FILES)
    assert clock.slept == []


def test_ask_not_json(monkeypatch, clock):
    monkeypatch.setattr(web, "request", FakeWeb(ok("<html>", 200)))

    with pytest.raises(ApiError, match="200: <html>"):
        client(clock).ask(FILES)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"detail": {"message": "spent"}}, "spent"),
        ({"message": "bare"}, "bare"),
        (
            {"detail": [{"loc": ["body", "files"], "msg": "too long"}]},
            "body.files: too long",
        ),
        ({"detail": [{}]}, ": invalid"),
        ({"detail": "Not Found"}, "Not Found"),
        ({"detail": {}}, "no details"),
        ({"detail": []}, "no details"),
        ("x" * 400, "x" * 300),
        ("", "no details"),
        (None, "no details"),
    ],
)
def test_message(body, message):
    assert _message(body) == message


def test_review_polls_until_ready(monkeypatch, clock):
    fake = FakeWeb(review("indexing", retry_after=10), review("indexing"), review())
    monkeypatch.setattr(web, "request", fake)

    got = client(clock).review(FILES, wait=60)

    assert got.status == "ready"
    assert clock.slept == [10, module.POLL_SECONDS]


def test_review_gives_up_waiting(monkeypatch, clock):
    fake = FakeWeb(
        review("indexing", retry_after=20), review("indexing", retry_after=20)
    )
    monkeypatch.setattr(web, "request", fake)

    got = client(clock).review(FILES, wait=30)

    assert got.status == "indexing"
    assert clock.slept == [20]
    assert len(fake.calls) == 2
