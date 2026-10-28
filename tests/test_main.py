# tests/test_main.py

import json

import pytest
from helpers import CLI_ENGINE, FakeWeb, ok, review, update

from depdelta_cli import forgejo, gitlab, main, web
from depdelta_cli.api import DEFAULT_API_URL, _review
from depdelta_cli.main import failed, run

KEY = {"DEPDELTA_API_KEY": "dd_key"}


@pytest.fixture
def change(repo, commit):
    """base → head bumps eslint; the code uses CLIEngine."""
    base = commit({"package.json": '{"devDependencies": {"eslint": "8.57.0"}}'})
    head = commit(
        {
            "package.json": '{"devDependencies": {"eslint": "9.0.0"}}',
            "src/lint.ts": "import { CLIEngine } from 'eslint'\nnew CLIEngine()\n",
        }
    )
    return base, head


def gerrit_env(head: str) -> dict:
    return {
        **KEY,
        "GERRIT_PROJECT": "web",
        "GERRIT_CHANGE_NUMBER": "12",
        "GERRIT_PATCHSET_REVISION": head,
        "GERRIT_CHANGE_URL": "https://gerrit.test/c/web/+/12",
        "GERRIT_HTTP_USER": "bot",
        "GERRIT_HTTP_PASSWORD": "pw",
    }


def gitlab_env(base: str, head: str) -> dict:
    return {
        **KEY,
        "GITLAB_CI": "true",
        "CI_MERGE_REQUEST_IID": "7",
        "CI_COMMIT_SHA": head,
        "CI_MERGE_REQUEST_DIFF_BASE_SHA": base,
        "CI_API_V4_URL": "https://gl.test/api/v4",
        "CI_PROJECT_ID": "42",
        "CI_PROJECT_URL": "https://gl.test/acme/web",
        "GITLAB_TOKEN": "tok",
    }


def actions_env(tmp_path, base: str, head: str) -> dict:
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "number": 7,
                "pull_request": {"merge_base": base, "head": {"sha": head}},
            }
        )
    )
    return {
        **KEY,
        "FORGEJO_ACTIONS": "true",
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_SERVER_URL": "https://cb.test",
        "GITHUB_API_URL": "https://cb.test/api/v1",
        "GITHUB_REPOSITORY": "acme/web",
        "FORGEJO_TOKEN": "tok",
    }


def woodpecker_env(head: str) -> dict:
    return {
        **KEY,
        "CI": "woodpecker",
        "CI_FORGE_TYPE": "gitea",
        "CI_FORGE_URL": "https://gt.test",
        "CI_REPO": "acme/web",
        "CI_REPO_URL": "https://gt.test/acme/web",
        "CI_COMMIT_SHA": head,
        "CI_COMMIT_PULL_REQUEST": "7",
        "GITEA_TOKEN": "gtok",
    }


def test_run_gerrit_success(repo, change, monkeypatch, capsys):
    _, head = change
    fake = FakeWeb(
        review(updates=[update([CLI_ENGINE])]),
        review(updates=[update([CLI_ENGINE])], body="DepDelta review: Breaking"),
        ok({}),
    )
    monkeypatch.setattr(web, "request", fake)

    assert run(["--repo", str(repo)], gerrit_env(head)) == 0

    first, second, posted = fake.calls
    assert first["url"] == f"{DEFAULT_API_URL}/ci/reviews"
    assert first["body"]["format"] == "text"
    assert [f["path"] for f in first["body"]["files"]] == ["package.json"]
    assert second["body"]["usage"][0]["hits"] == [
        {"path": "src/lint.ts", "line": 2, "symbol": "CLIEngine", "change": "removed"}
    ]
    assert posted["url"] == (
        f"https://gerrit.test/a/changes/web~12/revisions/{head}/review"
    )
    assert posted["body"]["message"] == "DepDelta review: Breaking"
    err = capsys.readouterr().err
    assert "Usage check: 1 uses found." in err
    assert "Posted the review on the Gerrit change." in err


def test_run_gitlab_success(repo, change, monkeypatch, capsys):
    base, head = change
    fake = FakeWeb(review(updates=[update()]), ok([]), ok({"id": 1}, 201))
    monkeypatch.setattr(web, "request", fake)

    env = {**gitlab_env(base, head), "DEPDELTA_API_URL": "https://api.test/v1"}
    assert run(["--repo", str(repo)], env) == 0

    asked, _, added = fake.calls
    assert asked["url"] == "https://api.test/v1/ci/reviews"
    assert asked["body"]["format"] == "markdown"
    assert asked["body"]["source_url"] == f"https://gl.test/acme/web/-/blob/{head}"
    assert added["body"] == {"body": "### DepDelta review"}
    assert "Review note added on the merge request." in capsys.readouterr().err


def test_run_print_by_hand(repo, change, monkeypatch, capsys):
    base, head = change
    monkeypatch.setattr(web, "request", FakeWeb(review(updates=[update()])))

    code = run(
        ["--repo", str(repo), "--base", base, "--head", head, "--format", "text"],
        KEY,
    )

    assert code == 0
    out = capsys.readouterr()
    assert out.out == "### DepDelta review\n"
    assert "🔴 Breaking (1 updates)." in out.err


def test_run_print_in_ci(repo, change, monkeypatch, capsys):
    base, head = change
    fake = FakeWeb(review())
    monkeypatch.setattr(web, "request", fake)

    assert run(["--repo", str(repo), "--print"], gitlab_env(base, head)) == 0
    assert len(fake.calls) == 1
    assert capsys.readouterr().out == "### DepDelta review\n"


def test_run_fail_on(repo, change, monkeypatch):
    base, head = change
    monkeypatch.setattr(web, "request", FakeWeb(review(updates=[update()])))

    args = ["--repo", str(repo), "--base", base, "--head", head]
    assert run([*args, "--fail-on", "breaking"], KEY) == 1


def test_run_nothing_to_review(repo, commit, monkeypatch, capsys):
    base = commit({"a.ts": "1"})
    head = commit({"a.ts": "2"})
    monkeypatch.setattr(web, "request", FakeWeb())

    assert run(["--repo", str(repo), "--base", base, "--head", head], {}) == 0
    assert "nothing to review" in capsys.readouterr().err


def test_run_caps_the_files(repo, commit, monkeypatch, capsys):
    monkeypatch.setattr(main, "MAX_FILES", 1)
    base = commit({})
    head = commit({"a/package.json": "{}", "b/package.json": "{}"})
    fake = FakeWeb(review())
    monkeypatch.setattr(web, "request", fake)

    assert run(["--repo", str(repo), "--base", base, "--head", head], KEY) == 0
    assert len(fake.calls[0]["body"]["files"]) == 1
    assert "2 manifests changed; reviewing the first 1." in capsys.readouterr().err


@pytest.mark.parametrize(
    ("args", "env", "message"),
    [
        (["--base", "x"], {}, "Pass both --base and --head."),
        ([], {}, "No change found"),
    ],
)
def test_run_usage_errors(repo, args, env, message, capsys):
    assert run(["--repo", str(repo), *args], env) == 2
    assert message in capsys.readouterr().err


def test_run_without_a_key(repo, change, capsys):
    base, head = change

    assert run(["--repo", str(repo), "--base", base, "--head", head], {}) == 2
    assert "Set DEPDELTA_API_KEY" in capsys.readouterr().err


def test_run_gerrit_without_credentials(repo, change, monkeypatch, capsys):
    _, head = change
    monkeypatch.setattr(web, "request", FakeWeb(review()))
    env = gerrit_env(head)
    del env["GERRIT_HTTP_PASSWORD"]

    assert run(["--repo", str(repo)], env) == 2
    assert "Set GERRIT_HTTP_PASSWORD" in capsys.readouterr().err


def test_run_gerrit_cuts_long_reviews(repo, change, monkeypatch):
    _, head = change
    monkeypatch.setattr(main.gerrit, "MAX_MESSAGE", 100)
    fake = FakeWeb(review(updates=[update()], body="x" * 500), ok({}))
    monkeypatch.setattr(web, "request", fake)

    assert run(["--repo", str(repo)], gerrit_env(head)) == 0
    message = fake.calls[1]["body"]["message"]
    assert message.endswith(update()["url"])


def test_run_gerrit_cut_without_updates(repo, change, monkeypatch):
    _, head = change
    monkeypatch.setattr(main.gerrit, "MAX_MESSAGE", 100)
    fake = FakeWeb(review(body="x" * 500), ok({}))
    monkeypatch.setattr(web, "request", fake)

    assert run(["--repo", str(repo)], gerrit_env(head)) == 0
    assert fake.calls[1]["body"]["message"].endswith("\n\n…")


def test_run_gitlab_post_fails(repo, change, monkeypatch, capsys):
    base, head = change
    monkeypatch.setattr(web, "request", FakeWeb(review(), ok({"message": "x"}, 401)))

    assert run(["--repo", str(repo)], gitlab_env(base, head)) == 2
    assert "GitLab answered 401" in capsys.readouterr().err


def test_run_gitlab_without_token(repo, change, monkeypatch, capsys):
    base, head = change
    monkeypatch.setattr(web, "request", FakeWeb(review()))
    env = gitlab_env(base, head)
    del env["GITLAB_TOKEN"]

    assert run(["--repo", str(repo)], env) == 2
    assert "Set GITLAB_TOKEN" in capsys.readouterr().err


def test_run_network_failure_posting(repo, change, monkeypatch, capsys):
    base, head = change
    monkeypatch.setattr(web, "request", FakeWeb(review(), web.HttpError("down")))

    assert run(["--repo", str(repo)], gitlab_env(base, head)) == 2
    assert "down" in capsys.readouterr().err


def test_run_unknown_target(repo, change, monkeypatch):
    # A Change for neither platform posts nothing.
    base, head = change
    monkeypatch.setattr(web, "request", FakeWeb(review()))
    real = main.detect_change

    def odd(env):
        found = real(env)
        return type(found)(found.platform, found.base, found.head, None, object())

    monkeypatch.setattr(main, "detect_change", odd)

    assert run(["--repo", str(repo)], gitlab_env(base, head)) == 0


@pytest.mark.parametrize(
    ("verdicts", "fail_on", "expected"),
    [
        (["breaking"], "never", False),
        (["review"], "breaking", False),
        (["breaking"], "breaking", True),
        (["safe", "review"], "review", True),
        (["unknown"], "review", False),
        ([None], "safe", False),
        ([], "safe", False),
    ],
)
def test_failed(verdicts, fail_on, expected):
    got = review(updates=[{"verdict": v} for v in verdicts])
    assert failed(_review(got.body["data"]), fail_on) is expected  # type: ignore[index]


def test_marker_matches_the_api():
    assert gitlab.MARKER == "<!-- depdelta:review -->"
    assert forgejo.MARKER == gitlab.MARKER


def test_run_forgejo_actions_success(repo, change, tmp_path, monkeypatch, capsys):
    base, head = change
    fake = FakeWeb(review(updates=[update()]), ok([]), ok({"id": 1}, 201))
    monkeypatch.setattr(web, "request", fake)

    assert run(["--repo", str(repo)], actions_env(tmp_path, base, head)) == 0

    asked, listing, added = fake.calls
    assert asked["body"]["format"] == "markdown"
    assert [f["path"] for f in asked["body"]["files"]] == ["package.json"]
    assert asked["body"]["source_url"] == f"https://cb.test/acme/web/src/commit/{head}"
    assert listing["url"] == "https://cb.test/api/v1/repos/acme/web/issues/7/comments"
    assert added["headers"] == {"Authorization": "token tok"}
    assert added["body"] == {"body": "### DepDelta review"}
    assert "Review comment added on the pull request." in capsys.readouterr().err


def test_run_woodpecker_asks_for_the_merge_base(repo, change, monkeypatch, capsys):
    base, head = change
    fake = FakeWeb(
        ok({"merge_base": base}),
        review(updates=[update()]),
        ok([{"id": 4, "body": forgejo.MARKER}]),
        ok({"id": 4}),
    )
    monkeypatch.setattr(web, "request", fake)

    assert run(["--repo", str(repo)], woodpecker_env(head)) == 0

    pull, asked, _, edited = fake.calls
    assert pull["url"] == "https://gt.test/api/v1/repos/acme/web/pulls/7"
    assert pull["headers"] == {"Authorization": "token gtok"}
    assert [f["path"] for f in asked["body"]["files"]] == ["package.json"]
    assert edited["url"] == "https://gt.test/api/v1/repos/acme/web/issues/comments/4"
    assert "Review comment updated on the pull request." in capsys.readouterr().err


def test_run_forgejo_actions_token_fallback(repo, change, tmp_path, monkeypatch):
    base, head = change
    fake = FakeWeb(review(), ok([]), ok({"id": 1}, 201))
    monkeypatch.setattr(web, "request", fake)
    env = actions_env(tmp_path, base, head)
    del env["FORGEJO_TOKEN"]
    env["GITHUB_TOKEN"] = "ghtok"

    assert run(["--repo", str(repo)], env) == 0
    assert fake.calls[2]["headers"] == {"Authorization": "token ghtok"}


def test_run_forgejo_without_token(repo, change, tmp_path, monkeypatch, capsys):
    base, head = change
    monkeypatch.setattr(web, "request", FakeWeb(review()))
    env = {**actions_env(tmp_path, base, head), "FORGEJO_TOKEN": " "}

    assert run(["--repo", str(repo)], env) == 2
    assert "Set FORGEJO_TOKEN (or GITEA_TOKEN)" in capsys.readouterr().err


def test_run_woodpecker_without_token(repo, change, monkeypatch, capsys):
    _, head = change
    fake = FakeWeb()
    monkeypatch.setattr(web, "request", fake)
    env = woodpecker_env(head)
    del env["GITEA_TOKEN"]

    assert run(["--repo", str(repo)], env) == 2
    assert fake.calls == []
    assert "Set FORGEJO_TOKEN (or GITEA_TOKEN)" in capsys.readouterr().err


def test_run_woodpecker_merge_base_refused(repo, change, monkeypatch, capsys):
    _, head = change
    monkeypatch.setattr(web, "request", FakeWeb(ok({"message": "not found"}, 404)))

    assert run(["--repo", str(repo)], woodpecker_env(head)) == 2
    err = capsys.readouterr().err
    assert "Forgejo/Gitea answered 404 showing the pull request" in err


def test_run_forgejo_post_fails(repo, change, tmp_path, monkeypatch, capsys):
    base, head = change
    fake = FakeWeb(review(), ok({"message": "token is required"}, 401))
    monkeypatch.setattr(web, "request", fake)

    assert run(["--repo", str(repo)], actions_env(tmp_path, base, head)) == 2
    assert "Forgejo/Gitea answered 401 listing comments" in capsys.readouterr().err


def test_run_forgejo_not_a_pull_request(repo, tmp_path, capsys):
    event = tmp_path / "push.json"
    event.write_text(json.dumps({"ref": "refs/heads/main"}))
    env = {**KEY, "GITEA_ACTIONS": "true", "GITHUB_EVENT_PATH": str(event)}

    assert run(["--repo", str(repo)], env) == 2
    assert "Not a pull request workflow" in capsys.readouterr().err


def _blocked(blocked: bool = True, notes: list | None = None):
    return ok(
        {
            "data": {
                "status": "ready",
                "label": "🟢 Safe",
                "body": "### DepDelta review",
                "verdict": "safe",
                "updates": [],
                "blocked": blocked,
                "notes": notes or [],
            }
        }
    )


def test_run_sends_the_config_and_blocks(repo, commit, monkeypatch, capsys):
    base = commit({"package.json": '{"dependencies": {}}'})
    head = commit(
        {
            "package.json": '{"dependencies": {"runner": "1.0.0"}}',
            ".depdelta.yml": "install_scripts: block\nextra: [\n",
        }
    )
    fake = FakeWeb(_blocked(notes=["not valid YAML; using the defaults"]))
    monkeypatch.setattr(web, "request", fake)

    code = run(["--repo", str(repo), "--base", base, "--head", head], KEY)

    assert code == 1
    assert fake.calls[0]["body"]["config"] == "install_scripts: block\nextra: [\n"
    err = capsys.readouterr().err
    assert ".depdelta.yml: not valid YAML; using the defaults." in err
    assert "sets install_scripts: block" in err


def test_run_not_blocked_passes(repo, commit, monkeypatch):
    base = commit({"package.json": '{"dependencies": {}}'})
    head = commit({"package.json": '{"dependencies": {"runner": "1.0.0"}}'})
    fake = FakeWeb(_blocked(blocked=False))
    monkeypatch.setattr(web, "request", fake)

    assert run(["--repo", str(repo), "--base", base, "--head", head], KEY) == 0
    assert "config" not in fake.calls[0]["body"]
