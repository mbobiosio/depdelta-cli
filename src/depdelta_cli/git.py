# src/depdelta_cli/git.py
#
# What the change touched, read from the CI checkout with git: the changed
# manifests at both ends, and the source files at the change's head (the
# working tree, which CI has checked out).

import os
import subprocess
from dataclasses import dataclass

from depdelta_cli.manifests import is_manifest, skipped
from depdelta_cli.usage import SOURCE_EXTENSIONS

#: Source files read for the usage check, the size of each, and in all.
MAX_SOURCE_FILES = 5000
MAX_SOURCE_FILE_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
#: A line this long is generated or minified code: the file is skipped.
MAX_LINE_LENGTH = 5000


class GitError(Exception):
    """git failed (not a repository, an unknown revision)."""


@dataclass(frozen=True)
class ChangedFile:
    path: str
    #: None when the change adds it.
    base: str | None
    #: None when the change deletes it.
    head: str | None


def _git(repo: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, check=False)


def _out(repo: str, *args: str) -> str:
    result = _git(repo, *args)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git {' '.join(args)}: {message}")
    return result.stdout.decode("utf-8", "replace")


def _show(repo: str, rev: str, path: str) -> str | None:
    """The file at ``rev``, or None when it isn't there."""
    result = _git(repo, "show", f"{rev}:{path}")
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace")


def changed_manifests(repo: str, base: str, head: str) -> list[ChangedFile]:
    """The manifests and lockfiles the change touched, at both ends."""
    names = _out(repo, "diff", "--name-only", "--no-renames", base, head, "--")
    paths = [p for p in names.splitlines() if p and is_manifest(p)]
    return [
        ChangedFile(path, _show(repo, base, path), _show(repo, head, path))
        for path in paths
    ]


@dataclass(frozen=True)
class SourceFiles:
    #: (path, text) of each file read.
    files: list[tuple[str, str]]
    #: More files than the limits: the usage check saw only some.
    too_large: bool


def ensure_commit(repo: str, rev: str) -> None:
    """Fetch ``rev`` when a shallow clone doesn't have it."""
    if _git(repo, "cat-file", "-e", f"{rev}^{{commit}}").returncode == 0:
        return
    _out(repo, "fetch", "--quiet", "--depth=1", "origin", rev)


def source_files(repo: str, ecosystems: set[str]) -> SourceFiles:
    """The checkout's tracked source files for ``ecosystems``. Vendored and
    build directories, type declarations, oversized and minified files are
    left out."""
    extensions = tuple(
        ext for eco in sorted(ecosystems) for ext in SOURCE_EXTENSIONS.get(eco, ())
    )
    if not extensions:
        return SourceFiles([], False)
    files: list[tuple[str, str]] = []
    size = 0
    for path in _out(repo, "ls-files", "-z").split("\0"):
        if not path.endswith(extensions) or path.endswith(".d.ts") or skipped(path):
            continue
        if len(files) >= MAX_SOURCE_FILES or size >= MAX_SOURCE_BYTES:
            return SourceFiles(files, True)
        full = os.path.join(repo, path)
        try:
            if os.path.getsize(full) > MAX_SOURCE_FILE_BYTES:
                continue
            with open(full, "rb") as handle:
                raw = handle.read()
        except OSError:
            # Listed but not checked out (a sparse checkout, a submodule).
            continue
        size += len(raw)
        text = raw.decode("utf-8", "replace")
        if any(len(line) > MAX_LINE_LENGTH for line in text.splitlines()):
            continue
        files.append((path, text))
    return SourceFiles(files, False)
