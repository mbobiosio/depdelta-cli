# tests/test_env.py

import pytest

from depdelta_cli.env import (
    Change,
    EnvError,
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
