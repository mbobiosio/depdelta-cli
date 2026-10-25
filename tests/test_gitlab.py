# tests/test_gitlab.py

import pytest
from helpers import FakeWeb, ok

from depdelta_cli import gitlab, web
from depdelta_cli.env import GitLabMergeRequest

MR = GitLabMergeRequest("https://gl.test/api/v4", "acme/web", "7")
NOTES = "https://gl.test/api/v4/projects/acme%2Fweb/merge_requests/7/notes"


def test_post_adds_a_note(monkeypatch):
    fake = FakeWeb(ok([{"id": 1, "body": "lgtm"}]), ok({"id": 2}, 201))
    monkeypatch.setattr(web, "request", fake)

    assert gitlab.post(MR, "<!-- depdelta:review -->\nreview", "tok") == "added"
    listing, added = fake.calls
    assert listing["url"] == (
        f"{NOTES}?sort=desc&order_by=created_at&per_page=100&page=1"
    )
    assert listing["headers"] == {"PRIVATE-TOKEN": "tok"}
    assert (added["method"], added["url"]) == ("POST", NOTES)
    assert added["body"] == {"body": "<!-- depdelta:review -->\nreview"}


def test_post_updates_the_earlier_note(monkeypatch):
    fake = FakeWeb(ok([{"id": 5, "body": f"{gitlab.MARKER}\nold"}]), ok({"id": 5}))
    monkeypatch.setattr(web, "request", fake)

    assert gitlab.post(MR, "new", "tok") == "updated"
    assert (fake.calls[1]["method"], fake.calls[1]["url"]) == ("PUT", f"{NOTES}/5")


def test_find_note_pages(monkeypatch):
    monkeypatch.setattr(gitlab, "PER_PAGE", 1)
    fake = FakeWeb(ok([{"id": 1, "body": "x"}]), ok([{"id": 2, "body": gitlab.MARKER}]))
    monkeypatch.setattr(web, "request", fake)

    assert gitlab.find_note(MR, "tok") == 2
    assert fake.calls[1]["url"].endswith("&per_page=1&page=2")


def test_find_note_stops_after_max_pages(monkeypatch):
    monkeypatch.setattr(gitlab, "PER_PAGE", 1)
    monkeypatch.setattr(gitlab, "MAX_PAGES", 2)
    fake = FakeWeb(ok([{"id": 1}]), ok([{"id": 2}]))
    monkeypatch.setattr(web, "request", fake)

    assert gitlab.find_note(MR, "tok") is None
    assert len(fake.calls) == 2


def test_find_note_odd_listing(monkeypatch):
    monkeypatch.setattr(web, "request", FakeWeb(ok({"not": "a list"})))

    assert gitlab.find_note(MR, "tok") is None


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"message": "401 Unauthorized"}, "401 Unauthorized"),
        ({"error": "insufficient_scope"}, "insufficient_scope"),
        ({"other": 1}, "{'other': 1}"),
        ("text", "text"),
        (None, ""),
    ],
)
def test_post_refused(monkeypatch, body, detail):
    monkeypatch.setattr(web, "request", FakeWeb(ok(body, 403)))

    with pytest.raises(gitlab.GitLabError, match="403 listing notes") as error:
        gitlab.post(MR, "b", "tok")
    assert str(error.value).endswith(f": {detail}")


def test_post_add_refused(monkeypatch):
    monkeypatch.setattr(web, "request", FakeWeb(ok([]), ok({"message": "no"}, 404)))

    with pytest.raises(gitlab.GitLabError, match="404 adding the note: no"):
        gitlab.post(MR, "b", "tok")


def test_post_edit_refused(monkeypatch):
    fake = FakeWeb(ok([{"id": 5, "body": gitlab.MARKER}]), ok({"message": "no"}, 403))
    monkeypatch.setattr(web, "request", fake)

    with pytest.raises(gitlab.GitLabError, match="403 editing the note: no"):
        gitlab.post(MR, "b", "tok")
