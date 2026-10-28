# tests/test_env.py

import json

import pytest

from depdelta_cli.env import (
    Change,
    EnvError,
    ForgejoPullRequest,
    GerritChange,
    GitLabMergeRequest,
    _gerrit_root,
    detect,
)

GERRIT = {
    "GERRIT_PROJECT": "platform/web app",
    "GERRIT_CHANGE_NUMBER": "123",
    "GERRIT_PATCHSET_REVISION": "abc",
    "GERRIT_CHANGE_URL": "https://gerrit.example.com/c/platform/web/+/123",
}
GITLAB = {
    "GITLAB_CI": "true",
    "CI_MERGE_REQUEST_IID": "7",
    "CI_COMMIT_SHA": "def",
    "CI_MERGE_REQUEST_DIFF_BASE_SHA": "abc",
    "CI_API_V4_URL": "https://gitlab.example.com/api/v4/",
    "CI_PROJECT_ID": "42",
    "CI_PROJECT_URL": "https://gitlab.example.com/acme/web/",
}
ACTIONS = {
    "FORGEJO_ACTIONS": "true",
    "GITHUB_ACTIONS": "true",
    "GITHUB_SHA": "sha",
    "GITHUB_SERVER_URL": "https://codeberg.org/",
    "GITHUB_API_URL": "https://codeberg.org/api/v1/",
    "GITHUB_REPOSITORY": "acme/web",
}
PULL_EVENT = {
    "action": "opened",
    "number": 7,
    "pull_request": {
        "number": 7,
        "merge_base": "abc",
        "base": {"sha": "tip"},
        "head": {"sha": "def"},
    },
}
WOODPECKER = {
    "CI": "woodpecker",
    "CI_FORGE_TYPE": "forgejo",
    "CI_FORGE_URL": "https://codeberg.org/",
    "CI_REPO": "acme/web",
    "CI_REPO_URL": "https://codeberg.org/acme/web/",
    "CI_COMMIT_SHA": "def",
    "CI_COMMIT_PULL_REQUEST": "7",
    "CI_PIPELINE_EVENT": "pull_request",
}


@pytest.fixture
def actions(tmp_path):
    """The Actions variables, with ``event`` saved where GITHUB_EVENT_PATH
    points."""

    def env(event: object = PULL_EVENT, **extra: str) -> dict:
        path = tmp_path / "event.json"
        path.write_text(json.dumps(event))
        return {**ACTIONS, "GITHUB_EVENT_PATH": str(path), **extra}

    return env


def test_detect_gerrit_success():
    assert detect(GERRIT) == Change(
        platform="gerrit",
        base="abc^",
        head="abc",
        source_url=None,
        target=GerritChange(
            url="https://gerrit.example.com",
            change_id="platform%2Fweb%20app~123",
            revision="abc",
        ),
    )


def test_detect_gerrit_url_override():
    env = {**GERRIT, "DEPDELTA_GERRIT_URL": "https://review.internal/r/"}
    del env["GERRIT_CHANGE_URL"]

    target = detect(env).target

    assert isinstance(target, GerritChange)
    assert target.url == "https://review.internal/r"


def test_detect_gerrit_missing_variable():
    env = {**GERRIT, "GERRIT_PATCHSET_REVISION": " "}

    with pytest.raises(EnvError, match="GERRIT_PATCHSET_REVISION is not set"):
        detect(env)


@pytest.mark.parametrize(
    ("url", "root"),
    [
        ("https://g.example.com/c/a/b/+/1", "https://g.example.com"),
        ("https://g.example.com/r/c/a/+/1/", "https://g.example.com/r"),
        ("https://g.example.com/r/123", "https://g.example.com/r"),
        ("http://g.example.com:8080/123", "http://g.example.com:8080"),
    ],
)
def test_gerrit_root_success(url, root):
    assert _gerrit_root(url) == root


def test_detect_gitlab_success():
    assert detect(GITLAB) == Change(
        platform="gitlab",
        base="abc",
        head="def",
        source_url="https://gitlab.example.com/acme/web/-/blob/def",
        target=GitLabMergeRequest(
            api_url="https://gitlab.example.com/api/v4", project_id="42", iid="7"
        ),
    )


def test_detect_gitlab_without_project_url():
    env = {**GITLAB, "CI_PROJECT_URL": ""}

    assert detect(env).source_url is None


def test_detect_gitlab_not_a_merge_request():
    env = {**GITLAB, "CI_MERGE_REQUEST_IID": ""}

    with pytest.raises(EnvError, match="Not a merge request pipeline"):
        detect(env)


def test_detect_no_change():
    with pytest.raises(EnvError, match="No change found"):
        detect({})


def test_detect_forgejo_actions_success(actions):
    assert detect(actions()) == Change(
        platform="forgejo",
        base="abc",
        head="def",
        source_url="https://codeberg.org/acme/web/src/commit/def",
        target=ForgejoPullRequest(
            api_url="https://codeberg.org/api/v1", repo="acme/web", index="7"
        ),
    )


def test_detect_gitea_actions_success(actions):
    env = actions(GITEA_ACTIONS="true")
    del env["FORGEJO_ACTIONS"]

    change = detect(env)

    assert change.platform == "forgejo"
    assert change.target == ForgejoPullRequest(
        "https://codeberg.org/api/v1", "acme/web", "7"
    )


def test_detect_forgejo_actions_base_without_merge_base(actions):
    pull = {"number": 7, "base": {"sha": "tip"}, "head": {"sha": "def"}}

    assert detect(actions({"pull_request": pull})).base == "tip"


def test_detect_forgejo_actions_without_commits(actions):
    # No base: the forge is asked later; no head: GITHUB_SHA.
    change = detect(actions({"number": 7, "pull_request": {"base": None}}))

    assert (change.base, change.head) == ("", "sha")


def test_detect_forgejo_actions_without_server_url(actions):
    assert detect(actions(GITHUB_SERVER_URL="")).source_url is None


@pytest.mark.parametrize(
    "event", [{"ref": "refs/heads/main"}, ["not", "an", "object"], None]
)
def test_detect_forgejo_actions_not_a_pull_request(actions, event):
    with pytest.raises(EnvError, match="Not a pull request workflow"):
        detect(actions(event))


def test_detect_forgejo_actions_without_a_number(actions):
    with pytest.raises(EnvError, match="no pull request number"):
        detect(actions({"pull_request": {"head": {"sha": "def"}}}))


def test_detect_forgejo_actions_unreadable_payload(actions, tmp_path):
    env = actions(GITHUB_EVENT_PATH=str(tmp_path / "missing.json"))

    with pytest.raises(EnvError, match="Can't read the event payload"):
        detect(env)


def test_detect_forgejo_actions_payload_not_json(actions, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{")

    with pytest.raises(EnvError, match="Can't read the event payload"):
        detect(actions(GITHUB_EVENT_PATH=str(path)))


@pytest.mark.parametrize(
    "name", ["GITHUB_EVENT_PATH", "GITHUB_REPOSITORY", "GITHUB_API_URL"]
)
def test_detect_forgejo_actions_missing_variable(actions, name):
    env = actions()
    del env[name]

    with pytest.raises(EnvError, match=f"{name} is not set"):
        detect(env)


@pytest.mark.parametrize("forge", ["forgejo", "gitea"])
def test_detect_woodpecker_success(forge):
    assert detect({**WOODPECKER, "CI_FORGE_TYPE": forge}) == Change(
        platform="forgejo",
        base="",
        head="def",
        source_url="https://codeberg.org/acme/web/src/commit/def",
        target=ForgejoPullRequest(
            api_url="https://codeberg.org/api/v1", repo="acme/web", index="7"
        ),
    )


def test_detect_woodpecker_without_repo_url():
    assert detect({**WOODPECKER, "CI_REPO_URL": ""}).source_url is None


def test_detect_woodpecker_not_a_pull_request():
    env = {**WOODPECKER, "CI_COMMIT_PULL_REQUEST": "", "CI_PIPELINE_EVENT": "push"}

    with pytest.raises(EnvError, match="Not a pull request pipeline"):
        detect(env)


@pytest.mark.parametrize("name", ["CI_COMMIT_SHA", "CI_FORGE_URL", "CI_REPO"])
def test_detect_woodpecker_missing_variable(name):
    env = {**WOODPECKER, name: ""}

    with pytest.raises(EnvError, match=f"{name} is not set"):
        detect(env)


@pytest.mark.parametrize(
    "env",
    [
        {**WOODPECKER, "CI_FORGE_TYPE": "github"},
        {**WOODPECKER, "CI": "true"},
        {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_PATH": "/x"},
    ],
)
def test_detect_unsupported_ci(env):
    with pytest.raises(EnvError, match="No change found"):
        detect(env)
