# src/depdelta_cli/forgejo.py
#
# The review as one pull request comment on Forgejo or Gitea (Codeberg
# included: they share one API), found by its marker and edited in place on
# later runs, as the GitLab note is.

from urllib.parse import quote

from depdelta_cli import web
from depdelta_cli.env import ForgejoPullRequest
from depdelta_cli.gitlab import MARKER


class ForgejoError(Exception):
    """Forgejo or Gitea refused to show the pull request, or to list, add or
    edit the comment."""


def _repo_url(pr: ForgejoPullRequest) -> str:
    return f"{pr.api_url}/repos/{quote(pr.repo, safe='/')}"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"token {token}"}


def _check(reply: web.Response, doing: str) -> None:
    # Editing a comment can answer 204.
    if reply.status not in (200, 201, 204):
        raise ForgejoError(
            f"Forgejo/Gitea answered {reply.status} {doing}: {_detail(reply.body)}"
        )


def _detail(body: object) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body)[:300]
    return str(body or "")[:300]


def merge_base(pr: ForgejoPullRequest, token: str) -> str:
    """Where the pull request starts, for a CI that doesn't say."""
    reply = web.request(
        "GET", f"{_repo_url(pr)}/pulls/{pr.index}", headers=_headers(token)
    )
    _check(reply, "showing the pull request")
    pull = reply.body if isinstance(reply.body, dict) else {}
    base = pull.get("merge_base") or (pull.get("base") or {}).get("sha")
    if not base:
        raise ForgejoError("Forgejo/Gitea gave no base commit for the pull request.")
    return str(base)


def find_comment(pr: ForgejoPullRequest, token: str) -> int | None:
    """The id of the newest comment carrying the marker, if one was posted.
    The API lists every comment at once, oldest first."""
    reply = web.request(
        "GET",
        f"{_repo_url(pr)}/issues/{pr.index}/comments",
        headers=_headers(token),
    )
    _check(reply, "listing comments")
    comments = reply.body if isinstance(reply.body, list) else []
    for comment in reversed(comments):
        if MARKER in str(comment.get("body", "")):
            return int(comment["id"])
    return None


def post(pr: ForgejoPullRequest, body: str, token: str) -> str:
    """Edit the earlier comment, or add one. Says which."""
    existing = find_comment(pr, token)
    if existing is None:
        reply = web.request(
            "POST",
            f"{_repo_url(pr)}/issues/{pr.index}/comments",
            body={"body": body},
            headers=_headers(token),
        )
        _check(reply, "adding the comment")
        return "added"
    reply = web.request(
        "PATCH",
        f"{_repo_url(pr)}/issues/comments/{existing}",
        body={"body": body},
        headers=_headers(token),
    )
    _check(reply, "editing the comment")
    return "updated"
