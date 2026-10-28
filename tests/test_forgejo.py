# tests/test_forgejo.py

import pytest
from helpers import FakeWeb, ok

from depdelta_cli import forgejo, web
from depdelta_cli.env import ForgejoPullRequest

PR = ForgejoPullRequest("https://cb.test/api/v1", "acme/web", "7")
REPO = "https://cb.test/api/v1/repos/acme/web"
COMMENTS = f"{REPO}/issues/7/comments"


def test_post_adds_a_comment(monkeypatch):
    fake = FakeWeb(ok([{"id": 1, "body": "lgtm"}]), ok({"id": 2}, 201))
    monkeypatch.setattr(web, "request", fake)

    assert forgejo.post(PR, "<!-- depdelta:review -->\nreview", "tok") == "added"
    listing, added = fake.calls
    assert (listing["method"], listing["url"]) == ("GET", COMMENTS)
    assert listing["headers"] == {"Authorization": "token tok"}
    assert (added["method"], added["url"]) == ("POST", COMMENTS)
    assert added["body"] == {"body": "<!-- depdelta:review -->\nreview"}
    assert added["headers"] == {"Authorization": "token tok"}


def test_post_updates_the_earlier_comment(monkeypatch):
    fake = FakeWeb(ok([{"id": 5, "body": f"{forgejo.MARKER}\nold"}]), ok({"id": 5}))
    monkeypatch.setattr(web, "request", fake)

    assert forgejo.post(PR, "new", "tok") == "updated"
    edited = fake.calls[1]
    assert (edited["method"], edited["url"]) == ("PATCH", f"{REPO}/issues/comments/5")
    assert edited["body"] == {"body": "new"}


def test_post_updates_when_the_edit_answers_no_content(monkeypatch):
    fake = FakeWeb(ok([{"id": 5, "body": forgejo.MARKER}]), ok(None, 204))
    monkeypatch.setattr(web, "request", fake)

    assert forgejo.post(PR, "same", "tok") == "updated"


def test_find_comment_newest_success(monkeypatch):
    listing = [
        {"id": 1, "body": forgejo.MARKER},
        {"id": 2, "body": "lgtm"},
        {"id": 3, "body": f"{forgejo.MARKER}\nnewer"},
    ]
    monkeypatch.setattr(web, "request", FakeWeb(ok(listing)))

    assert forgejo.find_comment(PR, "tok") == 3


def test_find_comment_odd_listing(monkeypatch):
    monkeypatch.setattr(web, "request", FakeWeb(ok({"not": "a list"})))

    assert forgejo.find_comment(PR, "tok") is None


def test_find_comment_quotes_the_repo(monkeypatch):
    fake = FakeWeb(ok([]))
    monkeypatch.setattr(web, "request", fake)

    forgejo.find_comment(ForgejoPullRequest("https://g.test/api/v1", "a b/c", "1"), "t")

    assert (
        fake.calls[0]["url"] == "https://g.test/api/v1/repos/a%20b/c/issues/1/comments"
    )


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"message": "token is required"}, "token is required"),
        ({"other": 1}, "{'other': 1}"),
        ("text", "text"),
        (None, ""),
    ],
)
def test_post_refused(monkeypatch, body, detail):
    monkeypatch.setattr(web, "request", FakeWeb(ok(body, 401)))

    with pytest.raises(forgejo.ForgejoError, match="401 listing comments") as error:
        forgejo.post(PR, "b", "tok")
    assert str(error.value).endswith(f": {detail}")


def test_post_add_refused(monkeypatch):
    monkeypatch.setattr(web, "request", FakeWeb(ok([]), ok({"message": "no"}, 403)))

    with pytest.raises(forgejo.ForgejoError, match="403 adding the comment: no"):
        forgejo.post(PR, "b", "tok")


def test_post_edit_refused(monkeypatch):
    fake = FakeWeb(ok([{"id": 5, "body": forgejo.MARKER}]), ok({"message": "no"}, 423))
    monkeypatch.setattr(web, "request", fake)

    with pytest.raises(forgejo.ForgejoError, match="423 editing the comment: no"):
        forgejo.post(PR, "b", "tok")


def test_merge_base_success(monkeypatch):
    fake = FakeWeb(ok({"merge_base": "mb", "base": {"sha": "tip"}}))
    monkeypatch.setattr(web, "request", fake)

    assert forgejo.merge_base(PR, "tok") == "mb"
    assert fake.calls == [
        {
            "method": "GET",
            "url": f"{REPO}/pulls/7",
            "body": None,
            "headers": {"Authorization": "token tok"},
        }
    ]


def test_merge_base_falls_back_to_the_base_commit(monkeypatch):
    monkeypatch.setattr(web, "request", FakeWeb(ok({"base": {"sha": "tip"}})))

    assert forgejo.merge_base(PR, "tok") == "tip"


@pytest.mark.parametrize("body", [{}, {"base": None}, {"merge_base": ""}, ["x"]])
def test_merge_base_missing(monkeypatch, body):
    monkeypatch.setattr(web, "request", FakeWeb(ok(body)))

    with pytest.raises(forgejo.ForgejoError, match="no base commit"):
        forgejo.merge_base(PR, "tok")


def test_merge_base_refused(monkeypatch):
    monkeypatch.setattr(web, "request", FakeWeb(ok({"message": "not found"}, 404)))

    with pytest.raises(
        forgejo.ForgejoError, match="404 showing the pull request: not found"
    ):
        forgejo.merge_base(PR, "tok")
