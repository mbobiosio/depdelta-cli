# src/depdelta_cli/bitbucket.py
#
# The review as one Bitbucket Cloud pull request comment, found by its marker
# and edited in place on later pipelines. Bitbucket shows HTML as text, so
# the review comes in plain CommonMark with a link-reference marker.

from urllib.parse import quote

from depdelta_cli import web
from depdelta_cli.env import BitbucketPullRequest

#: In both the HTML marker and the CommonMark one (depdelta-api render.py).
MARKER_TEXT = "depdelta:review"
PAGE_LENGTH = 100
#: Comment pages searched for the marker.
MAX_PAGES = 10


class BitbucketError(Exception):
    """Bitbucket refused to show the merge base, or to list, add or edit
    the comment."""


def _repo_url(pr: BitbucketPullRequest) -> str:
    return f"{pr.api_url}/repositories/{quote(pr.repo, safe='/')}"


def _comments_url(pr: BitbucketPullRequest) -> str:
    return f"{_repo_url(pr)}/pullrequests/{quote(pr.id, safe='')}/comments"


def _check(reply: web.Response, doing: str) -> None:
    if reply.status not in (200, 201):
        raise BitbucketError(
            f"Bitbucket answered {reply.status} {doing}: {_detail(reply.body)}"
        )


def _detail(body: object) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)[:300]
        return str(body)[:300]
    return str(body or "")[:300]


def merge_base(pr: BitbucketPullRequest, head: str, auth: str) -> str:
    """Where the pull request starts: the destination's and head's common
    ancestor."""
    revspec = f"{quote(pr.destination, safe='')}..{quote(head, safe='')}"
    reply = web.request(
        "GET",
        f"{_repo_url(pr)}/merge-base/{revspec}",
        headers={"Authorization": auth},
    )
    _check(reply, "finding the merge base")
    found = reply.body.get("hash") if isinstance(reply.body, dict) else None
    if not found:
        raise BitbucketError("Bitbucket gave no merge base for the pull request.")
    return str(found)


def find_comment(pr: BitbucketPullRequest, auth: str) -> int | None:
    """The id of the newest comment carrying the marker, if one was posted.
    Pages come oldest first; deleted comments don't count."""
    url: str | None = f"{_comments_url(pr)}?pagelen={PAGE_LENGTH}"
    found = None
    for _ in range(MAX_PAGES):
        if url is None:
            break
        reply = web.request("GET", url, headers={"Authorization": auth})
        _check(reply, "listing comments")
        page = reply.body if isinstance(reply.body, dict) else {}
        for comment in page.get("values") or []:
            raw = str((comment.get("content") or {}).get("raw") or "")
            if MARKER_TEXT in raw and not comment.get("deleted"):
                found = int(comment["id"])
        url = page.get("next")
    return found


def post(pr: BitbucketPullRequest, body: str, auth: str) -> str:
    """Edit the earlier comment, or add one. Says which."""
    existing = find_comment(pr, auth)
    content = {"content": {"raw": body}}
    headers = {"Authorization": auth}
    if existing is None:
        reply = web.request("POST", _comments_url(pr), body=content, headers=headers)
        _check(reply, "adding the comment")
        return "added"
    reply = web.request(
        "PUT", f"{_comments_url(pr)}/{existing}", body=content, headers=headers
    )
    _check(reply, "editing the comment")
    return "updated"
