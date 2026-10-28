# src/depdelta_cli/env.py
#
# Which change this CI job is for, read from the variables the CI sets:
# Jenkins with the Gerrit Trigger plugin, a GitLab merge request pipeline,
# or a Forgejo or Gitea pull request (their Actions, or Woodpecker).

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote, urlsplit


class EnvError(Exception):
    """The job isn't for a change, or a variable it needs is missing."""


@dataclass(frozen=True)
class GerritChange:
    #: Gerrit's web root: https://gerrit.example.com (or …/r).
    url: str
    #: REST id: `project~number`, URL-encoded.
    change_id: str
    revision: str


@dataclass(frozen=True)
class GitLabMergeRequest:
    #: https://gitlab.example.com/api/v4
    api_url: str
    project_id: str
    iid: str


@dataclass(frozen=True)
class ForgejoPullRequest:
    #: https://codeberg.org/api/v1
    api_url: str
    #: `owner/name`
    repo: str
    index: str


@dataclass(frozen=True)
class Change:
    platform: Literal["gerrit", "gitlab", "forgejo"]
    #: Empty when the CI doesn't say: the forge is asked (Woodpecker).
    base: str
    head: str
    #: Files' page at the head commit; uses link into it.
    source_url: str | None
    target: GerritChange | GitLabMergeRequest | ForgejoPullRequest


#: Woodpecker's CI_FORGE_TYPE values that speak the Forgejo/Gitea API.
FORGES = ("forgejo", "gitea")


def _need(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise EnvError(f"{name} is not set.")
    return value


def _gerrit_root(change_url: str) -> str:
    """Gerrit's web root from a change's URL: `…/c/project/+/123` (Gerrit
    3) or `…/123` (older)."""
    parts = urlsplit(change_url)
    path = parts.path.rstrip("/")
    if "/c/" in f"{path}/":
        path = path[: f"{path}/".index("/c/")]
    else:
        path = path.rsplit("/", 1)[0]
    return f"{parts.scheme}://{parts.netloc}{path}"


def gerrit(env: Mapping[str, str]) -> Change:
    """A Jenkins job started by the Gerrit Trigger plugin."""
    project = _need(env, "GERRIT_PROJECT")
    number = _need(env, "GERRIT_CHANGE_NUMBER")
    revision = _need(env, "GERRIT_PATCHSET_REVISION")
    url = env.get("DEPDELTA_GERRIT_URL", "").strip().rstrip("/")
    if not url:
        url = _gerrit_root(_need(env, "GERRIT_CHANGE_URL"))
    return Change(
        platform="gerrit",
        # A Gerrit change is one commit: its parent is what it changes.
        base=f"{revision}^",
        head=revision,
        source_url=None,
        target=GerritChange(
            url=url,
            change_id=f"{quote(project, safe='')}~{number}",
            revision=revision,
        ),
    )


def gitlab(env: Mapping[str, str]) -> Change:
    """A GitLab merge request pipeline."""
    iid = env.get("CI_MERGE_REQUEST_IID", "").strip()
    if not iid:
        raise EnvError(
            "Not a merge request pipeline: run the job on merge requests "
            "(rules: - if: $CI_PIPELINE_SOURCE == 'merge_request_event')."
        )
    head = _need(env, "CI_COMMIT_SHA")
    project_url = env.get("CI_PROJECT_URL", "").strip().rstrip("/")
    return Change(
        platform="gitlab",
        base=_need(env, "CI_MERGE_REQUEST_DIFF_BASE_SHA"),
        head=head,
        source_url=f"{project_url}/-/blob/{head}" if project_url else None,
        target=GitLabMergeRequest(
            api_url=_need(env, "CI_API_V4_URL").rstrip("/"),
            project_id=_need(env, "CI_PROJECT_ID"),
            iid=iid,
        ),
    )


def _event(path: str) -> dict:
    """The webhook payload Actions saved for the run."""
    try:
        with open(path, encoding="utf-8") as handle:
            event = json.load(handle)
    except (OSError, ValueError) as error:
        raise EnvError(f"Can't read the event payload {path}: {error}") from error
    return event if isinstance(event, dict) else {}


def _sha(end: object) -> str:
    """The commit of a pull request's `base` or `head` in a payload."""
    return str(end.get("sha") or "") if isinstance(end, dict) else ""


def forgejo_actions(env: Mapping[str, str]) -> Change:
    """A Forgejo or Gitea Actions workflow on a pull request. Both set the
    GITHUB_* variables; the pull request is in the event payload."""
    event = _event(_need(env, "GITHUB_EVENT_PATH"))
    pull = event.get("pull_request")
    if not isinstance(pull, dict):
        raise EnvError(
            "Not a pull request workflow: run the job on pull requests "
            "(on: pull_request)."
        )
    number = str(event.get("number") or pull.get("number") or "")
    if not number:
        raise EnvError("The event payload has no pull request number.")
    head = _sha(pull.get("head")) or _need(env, "GITHUB_SHA")
    server = env.get("GITHUB_SERVER_URL", "").strip().rstrip("/")
    repo = _need(env, "GITHUB_REPOSITORY")
    return Change(
        platform="forgejo",
        base=str(pull.get("merge_base") or "") or _sha(pull.get("base")),
        head=head,
        source_url=f"{server}/{repo}/src/commit/{head}" if server else None,
        target=ForgejoPullRequest(
            api_url=_need(env, "GITHUB_API_URL").rstrip("/"),
            repo=repo,
            index=number,
        ),
    )


def woodpecker(env: Mapping[str, str]) -> Change:
    """A Woodpecker pipeline for a Forgejo or Gitea pull request."""
    index = env.get("CI_COMMIT_PULL_REQUEST", "").strip()
    if not index:
        raise EnvError(
            "Not a pull request pipeline: run the step on pull requests "
            "(when: - event: pull_request)."
        )
    head = _need(env, "CI_COMMIT_SHA")
    repo_url = env.get("CI_REPO_URL", "").strip().rstrip("/")
    return Change(
        platform="forgejo",
        # Woodpecker names the target branch, not the commit the pull
        # request starts from: the forge is asked for its merge base.
        base="",
        head=head,
        source_url=f"{repo_url}/src/commit/{head}" if repo_url else None,
        target=ForgejoPullRequest(
            api_url=f"{_need(env, 'CI_FORGE_URL').rstrip('/')}/api/v1",
            repo=_need(env, "CI_REPO"),
            index=index,
        ),
    )


def detect(env: Mapping[str, str]) -> Change:
    """The change from the CI's variables."""
    if env.get("GERRIT_CHANGE_NUMBER"):
        return gerrit(env)
    if env.get("GITLAB_CI"):
        return gitlab(env)
    # Their runners also set GITHUB_ACTIONS; these tell them from GitHub.
    if env.get("FORGEJO_ACTIONS") or env.get("GITEA_ACTIONS"):
        return forgejo_actions(env)
    if env.get("CI") == "woodpecker" and env.get("CI_FORGE_TYPE") in FORGES:
        return woodpecker(env)
    raise EnvError(
        "No change found: run in Jenkins with the Gerrit Trigger plugin, in "
        "a GitLab merge request pipeline, or on a Forgejo or Gitea pull "
        "request (Actions or Woodpecker), or pass --base and --head."
    )
