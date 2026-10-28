# tests/test_bitbucket.py

import pytest
from helpers import FakeWeb, ok

from depdelta_cli import bitbucket, web
from depdelta_cli.env import BitbucketPullRequest

PR = BitbucketPullRequest("https://bb.test/2.0", "acme/web", "7", "dest1")
REPO = "https://bb.test/2.0/repositories/acme/web"
COMMENTS = f"{REPO}/pullrequests/7/comments"
AUTH = "Bearer tok"
MARKED = "[//]: # (depdelta:review)\n### DepDelta review"


def _comment(id_: int, raw: str, deleted: bool = False) -> dict:
    return {"id": id_, "content": {"raw": raw}, "deleted": deleted}


def test_merge_base_success(monkeypatch):
    fake = FakeWeb(ok({"hash": "base1"}))
    monkeypatch.setattr(web, "request", fake)

    assert bitbucket.merge_base(PR, "head1", AUTH) == "base1"
    assert fake.calls[0]["url"] == f"{REPO}/merge-base/dest1..head1"
    assert fake.calls[0]["headers"] == {"Authorization": AUTH}


@pytest.mark.parametrize("body", [{}, {"hash": ""}, ["odd"]])
def test_merge_base_missing(monkeypatch, body):
    monkeypatch.setattr(web, "request", FakeWeb(ok(body)))
    with pytest.raises(bitbucket.BitbucketError, match="no merge base"):
        bitbucket.merge_base(PR, "head1", AUTH)


def test_merge_base_refused(monkeypatch):
    error = {"type": "error", "error": {"message": "Repository not found"}}
    monkeypatch.setattr(web, "request", FakeWeb(ok(error, 404)))
    with pytest.raises(
        bitbucket.BitbucketError,
        match="404 finding the merge base: Repository not found",
    ):
        bitbucket.merge_base(PR, "head1", AUTH)


def test_post_adds_a_comment(monkeypatch):
    fake = FakeWeb(ok({"values": [_comment(1, "lgtm")]}), ok({"id": 2}, 201))
    monkeypatch.setattr(web, "request", fake)

    assert bitbucket.post(PR, MARKED, AUTH) == "added"
    listing, added = fake.calls
    assert listing["url"] == f"{COMMENTS}?pagelen=100"
    assert (added["method"], added["url"]) == ("POST", COMMENTS)
    assert added["body"] == {"content": {"raw": MARKED}}
    assert added["headers"] == {"Authorization": AUTH}


def test_post_updates_the_earlier_comment(monkeypatch):
    fake = FakeWeb(ok({"values": [_comment(5, MARKED)]}), ok({"id": 5}))
    monkeypatch.setattr(web, "request", fake)

    assert bitbucket.post(PR, "new", AUTH) == "updated"
    edited = fake.calls[1]
    assert (edited["method"], edited["url"]) == ("PUT", f"{COMMENTS}/5")
    assert edited["body"] == {"content": {"raw": "new"}}


def test_post_refused(monkeypatch):
    fake = FakeWeb(ok({"values": []}), ok("Forbidden", 403))
    monkeypatch.setattr(web, "request", fake)
    with pytest.raises(
        bitbucket.BitbucketError, match="403 adding the comment: Forbidden"
    ):
        bitbucket.post(PR, "x", AUTH)


def test_find_comment_follows_pages_newest_wins(monkeypatch):
    fake = FakeWeb(
        ok({"values": [_comment(1, MARKED)], "next": "https://bb.test/next"}),
        ok({"values": [_comment(2, "lgtm"), _comment(3, MARKED, deleted=True)]}),
    )
    monkeypatch.setattr(web, "request", fake)

    assert bitbucket.find_comment(PR, AUTH) == 1
    assert fake.calls[1]["url"] == "https://bb.test/next"


def test_find_comment_html_marker_counts(monkeypatch):
    listing = {"values": [_comment(1, "<!-- depdelta:review -->\nold")]}
    monkeypatch.setattr(web, "request", FakeWeb(ok(listing)))
    assert bitbucket.find_comment(PR, AUTH) == 1


def test_find_comment_stops_after_max_pages(monkeypatch):
    monkeypatch.setattr(bitbucket, "MAX_PAGES", 2)
    page = ok({"values": [], "next": "https://bb.test/next"})
    fake = FakeWeb(page, page)
    monkeypatch.setattr(web, "request", fake)

    assert bitbucket.find_comment(PR, AUTH) is None
    assert len(fake.calls) == 2


def test_find_comment_odd_listing(monkeypatch):
    monkeypatch.setattr(web, "request", FakeWeb(ok(["not", "a", "page"])))
    assert bitbucket.find_comment(PR, AUTH) is None


def test_find_comment_listing_refused(monkeypatch):
    monkeypatch.setattr(web, "request", FakeWeb(ok({"error": "bad"}, 401)))
    with pytest.raises(bitbucket.BitbucketError, match="401 listing comments"):
        bitbucket.find_comment(PR, AUTH)


def test_detail_plain_and_empty():
    assert bitbucket._detail({"error": "x"}) == "{'error': 'x'}"
    assert bitbucket._detail(None) == ""
