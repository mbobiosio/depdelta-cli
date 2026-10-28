# tests/test_azure.py

import pytest
from helpers import FakeWeb, ok

from depdelta_cli import azure, web
from depdelta_cli.env import AzurePullRequest

REPO = "https://dev.test/org/proj/_apis/git/repositories/r1"
PR = AzurePullRequest(REPO, "7")
PULL = f"{REPO}/pullRequests/7"
AUTH = "Bearer tok"
MARKED = "[//]: # (depdelta:review)\n### DepDelta review"


def _thread(id_: int, *comments: dict, deleted: bool = False) -> dict:
    return {"id": id_, "isDeleted": deleted, "comments": list(comments)}


def _comment(id_: int, content: str, deleted: bool = False) -> dict:
    return {"id": id_, "content": content, "isDeleted": deleted}


def test_merge_base_success(monkeypatch):
    fake = FakeWeb(
        ok({"lastMergeTargetCommit": {"commitId": "tgt"}}),
        ok({"value": [{"commitId": "base1"}]}),
    )
    monkeypatch.setattr(web, "request", fake)

    assert azure.merge_base(PR, "head1", AUTH) == "base1"
    pull, bases = fake.calls
    assert pull["url"] == f"{PULL}?api-version=7.1"
    assert bases["url"] == (
        f"{REPO}/commits/head1/mergebases?otherCommitId=tgt&api-version=7.1-preview.1"
    )
    assert bases["headers"] == {"Authorization": AUTH}


@pytest.mark.parametrize("pull", [{}, {"lastMergeTargetCommit": {}}, ["odd"]])
def test_merge_base_no_target(monkeypatch, pull):
    monkeypatch.setattr(web, "request", FakeWeb(ok(pull)))
    with pytest.raises(azure.AzureError, match="no target commit"):
        azure.merge_base(PR, "head1", AUTH)


@pytest.mark.parametrize("bases", [{"value": []}, {"value": [{}]}, ["odd"]])
def test_merge_base_none_found(monkeypatch, bases):
    fake = FakeWeb(ok({"lastMergeTargetCommit": {"commitId": "tgt"}}), ok(bases))
    monkeypatch.setattr(web, "request", fake)
    with pytest.raises(azure.AzureError, match="no merge base"):
        azure.merge_base(PR, "head1", AUTH)


def test_merge_base_refused(monkeypatch):
    error = {"message": "TF401019: The Git repository does not exist"}
    monkeypatch.setattr(web, "request", FakeWeb(ok(error, 404)))
    with pytest.raises(
        azure.AzureError, match="404 showing the pull request: TF401019"
    ):
        azure.merge_base(PR, "head1", AUTH)


def test_post_starts_a_thread(monkeypatch):
    fake = FakeWeb(ok({"value": [_thread(1, _comment(1, "lgtm"))]}), ok({"id": 9}))
    monkeypatch.setattr(web, "request", fake)

    assert azure.post(PR, MARKED, AUTH) == "added"
    listing, started = fake.calls
    assert listing["url"] == f"{PULL}/threads?api-version=7.1"
    assert (started["method"], started["url"]) == (
        "POST",
        f"{PULL}/threads?api-version=7.1",
    )
    assert started["body"] == {
        "comments": [{"parentCommentId": 0, "content": MARKED, "commentType": 1}],
        "status": "active",
    }
    assert started["headers"] == {"Authorization": AUTH}


def test_post_updates_the_earlier_comment(monkeypatch):
    fake = FakeWeb(ok({"value": [_thread(4, _comment(1, MARKED))]}), ok({"id": 1}))
    monkeypatch.setattr(web, "request", fake)

    assert azure.post(PR, "new", AUTH) == "updated"
    edited = fake.calls[1]
    assert (edited["method"], edited["url"]) == (
        "PATCH",
        f"{PULL}/threads/4/comments/1?api-version=7.1",
    )
    assert edited["body"] == {"content": "new"}


def test_post_refused(monkeypatch):
    fake = FakeWeb(ok({"value": []}), ok({"message": "denied"}, 403))
    monkeypatch.setattr(web, "request", fake)
    with pytest.raises(azure.AzureError, match="403 starting the thread: denied"):
        azure.post(PR, "x", AUTH)


def test_find_comment_skips_deleted_newest_wins(monkeypatch):
    threads = [
        _thread(1, _comment(1, MARKED)),
        _thread(2, _comment(1, MARKED), deleted=True),
        _thread(3, _comment(1, "lgtm"), _comment(2, MARKED, deleted=True)),
        _thread(5, _comment(1, "<!-- depdelta:review -->\nold")),
        {"id": 6},
    ]
    monkeypatch.setattr(web, "request", FakeWeb(ok({"value": threads})))
    assert azure.find_comment(PR, AUTH) == (5, 1)


def test_find_comment_odd_listing(monkeypatch):
    monkeypatch.setattr(web, "request", FakeWeb(ok(["odd"])))
    assert azure.find_comment(PR, AUTH) is None


def test_detail_plain_and_empty():
    assert azure._detail("Unauthorized") == "Unauthorized"
    assert azure._detail(None) == ""
    assert azure._detail({"x": 1}) == "{'x': 1}"
