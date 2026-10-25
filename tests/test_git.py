# tests/test_git.py

import pytest

from depdelta_cli import git as module
from depdelta_cli.git import (
    ChangedFile,
    GitError,
    SourceFiles,
    changed_manifests,
    ensure_commit,
    source_files,
)


def test_changed_manifests_success(repo, commit):
    base = commit({"package.json": '{"a": 1}', "Cargo.lock": "old", "x.ts": "1"})
    head = commit(
        {
            "package.json": '{"a": 2}',
            "Cargo.lock": None,
            "web/yarn.lock": "new",
            "x.ts": "2",
            "node_modules/y/package.json": "{}",
        }
    )

    files = changed_manifests(str(repo), base, head)

    assert sorted(files, key=lambda f: f.path) == [
        ChangedFile("Cargo.lock", "old", None),
        ChangedFile("package.json", '{"a": 1}', '{"a": 2}'),
        ChangedFile("web/yarn.lock", None, "new"),
    ]


def test_changed_manifests_unknown_revision(repo):
    with pytest.raises(GitError, match="git diff"):
        changed_manifests(str(repo), "nope", "HEAD")


def test_ensure_commit_present(repo, monkeypatch):
    calls = []
    monkeypatch.setattr(module, "_out", lambda *a: calls.append(a))

    ensure_commit(str(repo), "HEAD")

    assert calls == []


def test_ensure_commit_fetches_a_missing_one(repo, monkeypatch):
    calls = []
    monkeypatch.setattr(module, "_out", lambda *a: calls.append(a) or "")

    ensure_commit(str(repo), "abc123")

    assert calls == [(str(repo), "fetch", "--quiet", "--depth=1", "origin", "abc123")]


def test_ensure_commit_fetch_fails(repo):
    with pytest.raises(GitError, match="git fetch"):
        ensure_commit(str(repo), "abc123")


def test_source_files_success(repo, commit):
    commit(
        {
            "src/a.ts": "import x from 'y'\n",
            "src/b.d.ts": "declare const x: 1\n",
            "src/C.java": "class C {}\n",
            "dist/c.js": "x\n",
            "src/min.js": "x" * (module.MAX_LINE_LENGTH + 1),
            "src/bad.vue": "x",
            "README.md": "x",
        }
    )
    (repo / "src" / "bad.vue").write_bytes(b"<a>\xff</a>\n")

    found = source_files(str(repo), {"npm"})

    assert found == SourceFiles(
        [("src/a.ts", "import x from 'y'\n"), ("src/bad.vue", "<a>�</a>\n")],
        False,
    )


def test_source_files_no_extensions(repo):
    assert source_files(str(repo), {"pypi"}) == SourceFiles([], False)


def test_source_files_skips_big_and_missing_files(repo, commit, monkeypatch):
    monkeypatch.setattr(module, "MAX_SOURCE_FILE_BYTES", 3)
    commit({"big.ts": "12345", "ok.ts": "1", "gone.ts": "2"})
    (repo / "gone.ts").unlink()

    assert source_files(str(repo), {"npm"}).files == [("ok.ts", "1")]


def test_source_files_stops_at_the_file_cap(repo, commit, monkeypatch):
    monkeypatch.setattr(module, "MAX_SOURCE_FILES", 1)
    commit({"a.ts": "1", "b.ts": "2"})

    assert source_files(str(repo), {"npm"}) == SourceFiles([("a.ts", "1")], True)


def test_source_files_stops_at_the_byte_cap(repo, commit, monkeypatch):
    monkeypatch.setattr(module, "MAX_SOURCE_BYTES", 2)
    commit({"a.ts": "12", "b.ts": "3"})

    assert source_files(str(repo), {"npm"}) == SourceFiles([("a.ts", "12")], True)


def test_source_files_not_a_repository(tmp_path):
    with pytest.raises(GitError):
        source_files(str(tmp_path), {"npm"})


def test_show_missing_file(repo):
    assert module._show(str(repo), "HEAD", "nope") is None
