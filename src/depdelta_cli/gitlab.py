# src/depdelta_cli/gitlab.py
#
# The review as one merge request note, found by its marker and edited in
# place on later pipelines, as the GitHub App does with its PR comment.

from urllib.parse import quote

from depdelta_cli import web
from depdelta_cli.env import GitLabMergeRequest

#: depdelta-api `app/updates/utils/render.py` MARKER.
MARKER = "<!-- depdelta:review -->"
PER_PAGE = 100
#: Notes searched for the marker (newest first).
MAX_PAGES = 10


class GitLabError(Exception):
    """GitLab refused to list, add or edit the note."""


def _notes_url(mr: GitLabMergeRequest) -> str:
    project = quote(mr.project_id, safe="")
    return f"{mr.api_url}/projects/{project}/merge_requests/{mr.iid}/notes"


def _check(reply: web.Response, doing: str) -> None:
    if reply.status not in (200, 201):
        raise GitLabError(
            f"GitLab answered {reply.status} {doing}: {_detail(reply.body)}"
        )


def _detail(body: object) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or body)[:300]
    return str(body or "")[:300]


def find_note(mr: GitLabMergeRequest, token: str) -> int | None:
    """The id of the note carrying the marker, if one was posted."""
    headers = {"PRIVATE-TOKEN": token}
    for page in range(1, MAX_PAGES + 1):
        reply = web.request(
            "GET",
            f"{_notes_url(mr)}?sort=desc&order_by=created_at"
            f"&per_page={PER_PAGE}&page={page}",
            headers=headers,
        )
        _check(reply, "listing notes")
        notes = reply.body if isinstance(reply.body, list) else []
        for note in notes:
            if MARKER in str(note.get("body", "")):
                return int(note["id"])
        if len(notes) < PER_PAGE:
            return None
    return None


def post(mr: GitLabMergeRequest, body: str, token: str) -> str:
    """Edit the earlier note, or add one. Says which."""
    headers = {"PRIVATE-TOKEN": token}
    existing = find_note(mr, token)
    if existing is None:
        reply = web.request(
            "POST", _notes_url(mr), body={"body": body}, headers=headers
        )
        _check(reply, "adding the note")
        return "added"
    reply = web.request(
        "PUT", f"{_notes_url(mr)}/{existing}", body={"body": body}, headers=headers
    )
    _check(reply, "editing the note")
    return "updated"
