# src/depdelta_cli/azure.py
#
# The review as one Azure DevOps pull request thread, found by its marker
# and its first comment edited in place on later builds. A new thread is
# active (it can be resolved like any review comment). The review comes in
# plain CommonMark with a link-reference marker.

from urllib.parse import quote

from depdelta_cli import web
from depdelta_cli.env import AzurePullRequest

#: In both the HTML marker and the CommonMark one (depdelta-api render.py).
MARKER_TEXT = "depdelta:review"
API_VERSION = "api-version=7.1"
#: The merge-bases call is still a preview in 7.1.
MERGE_BASES_VERSION = "api-version=7.1-preview.1"


class AzureError(Exception):
    """Azure DevOps refused to show the pull request or its merge base, or
    to list, add or edit the thread."""


def _pr_url(pr: AzurePullRequest) -> str:
    return f"{pr.repo_url}/pullRequests/{quote(pr.id, safe='')}"


def _check(reply: web.Response, doing: str) -> None:
    if reply.status not in (200, 201):
        raise AzureError(
            f"Azure DevOps answered {reply.status} {doing}: {_detail(reply.body)}"
        )


def _detail(body: object) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body)[:300]
    return str(body or "")[:300]


def merge_base(pr: AzurePullRequest, head: str, auth: str) -> str:
    """Where the pull request starts: the target's last merged commit and
    the head's common ancestor."""
    headers = {"Authorization": auth}
    reply = web.request("GET", f"{_pr_url(pr)}?{API_VERSION}", headers=headers)
    _check(reply, "showing the pull request")
    pull = reply.body if isinstance(reply.body, dict) else {}
    target = (pull.get("lastMergeTargetCommit") or {}).get("commitId")
    if not target:
        raise AzureError("Azure DevOps gave no target commit for the pull request.")
    reply = web.request(
        "GET",
        f"{pr.repo_url}/commits/{quote(head, safe='')}/mergebases"
        f"?otherCommitId={quote(str(target), safe='')}&{MERGE_BASES_VERSION}",
        headers=headers,
    )
    _check(reply, "finding the merge base")
    bases = reply.body.get("value") if isinstance(reply.body, dict) else None
    if not bases or not bases[0].get("commitId"):
        raise AzureError("Azure DevOps gave no merge base for the pull request.")
    return str(bases[0]["commitId"])


def find_comment(pr: AzurePullRequest, auth: str) -> tuple[int, int] | None:
    """The (thread, comment) ids of the newest comment carrying the marker,
    if one was posted."""
    reply = web.request(
        "GET", f"{_pr_url(pr)}/threads?{API_VERSION}", headers={"Authorization": auth}
    )
    _check(reply, "listing threads")
    threads = reply.body.get("value") if isinstance(reply.body, dict) else None
    found = None
    for thread in threads or []:
        if thread.get("isDeleted"):
            continue
        for comment in thread.get("comments") or []:
            text = str(comment.get("content") or "")
            if MARKER_TEXT in text and not comment.get("isDeleted"):
                found = (int(thread["id"]), int(comment["id"]))
    return found


def post(pr: AzurePullRequest, body: str, auth: str) -> str:
    """Edit the earlier comment, or start a thread. Says which."""
    headers = {"Authorization": auth}
    existing = find_comment(pr, auth)
    if existing is None:
        reply = web.request(
            "POST",
            f"{_pr_url(pr)}/threads?{API_VERSION}",
            body={
                "comments": [{"parentCommentId": 0, "content": body, "commentType": 1}],
                "status": "active",
            },
            headers=headers,
        )
        _check(reply, "starting the thread")
        return "added"
    thread, comment = existing
    reply = web.request(
        "PATCH",
        f"{_pr_url(pr)}/threads/{thread}/comments/{comment}?{API_VERSION}",
        body={"content": body},
        headers=headers,
    )
    _check(reply, "editing the comment")
    return "updated"
