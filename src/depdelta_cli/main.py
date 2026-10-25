# src/depdelta_cli/main.py
#
# `depdelta`: review the change's dependency updates and post the review on
# the change (a Gerrit message, or a GitLab merge request note).
#
#   1. The manifests and lockfiles the change touched go to DepDelta.
#   2. DepDelta answers with each update's verdict and, for npm and Maven,
#      the declarations it removes or changes.
#   3. The command looks for those in the checkout and sends what it found;
#      the review then says where the code is hit.
#
# Exit status: 0 posted (or nothing to review), 1 the --fail-on verdict was
# met, 2 it couldn't review or post.

import argparse
import os
import sys
from collections.abc import Mapping, Sequence

from depdelta_cli import __version__, check, gerrit, gitlab, web
from depdelta_cli.api import DEFAULT_API_URL, ApiError, DepDelta, Review
from depdelta_cli.env import Change, EnvError, GerritChange, GitLabMergeRequest
from depdelta_cli.env import detect as detect_change
from depdelta_cli.git import GitError, changed_manifests, ensure_commit, source_files

#: depdelta-api pull_diff MAX_FILES: manifests reviewed per change.
MAX_FILES = 40
#: Verdicts from riskiest; --fail-on X fails on X and anything riskier.
VERDICTS = ("breaking", "review", "unknown", "safe")


class UsageError(Exception):
    """A required option or variable is missing."""


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="depdelta",
        description="Review a change's dependency updates with DepDelta and "
        "post the review on the Gerrit change or GitLab merge request.",
    )
    p.add_argument("--version", action="version", version=f"depdelta {__version__}")
    p.add_argument("--repo", default=".", help="The checkout (default: .)")
    p.add_argument("--base", help="Compare from this commit (default: from CI)")
    p.add_argument("--head", help="Compare to this commit (default: from CI)")
    p.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="Print the review instead of posting it",
    )
    p.add_argument(
        "--format",
        choices=("markdown", "text"),
        help="Review format (default: text for Gerrit, markdown otherwise)",
    )
    p.add_argument(
        "--wait",
        type=int,
        default=300,
        help="Seconds to wait for release notes to be read (default: 300)",
    )
    p.add_argument(
        "--fail-on",
        choices=("never", *VERDICTS),
        default="never",
        help="Exit 1 when an update's verdict is this or riskier (default: never)",
    )
    p.add_argument(
        "--api-url",
        default=None,
        help=f"DepDelta API (default: $DEPDELTA_API_URL or {DEFAULT_API_URL})",
    )
    return p


def _need(env: Mapping[str, str], name: str, why: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise UsageError(f"Set {name} {why}.")
    return value


def _change(args: argparse.Namespace, env: Mapping[str, str]) -> Change | None:
    """The CI's change, or None for --base/--head given by hand."""
    if args.base or args.head:
        if not (args.base and args.head):
            raise UsageError("Pass both --base and --head.")
        return None
    return detect_change(env)


def _review(
    client: DepDelta,
    args: argparse.Namespace,
    files: list,
    fmt: str,
    source_url: str | None,
) -> Review:
    review = client.review(files, fmt=fmt, source_url=source_url, wait=args.wait)
    wanted = check.ecosystems(review.updates)
    if not wanted:
        return review
    sources = source_files(args.repo, wanted)
    usage = check.usage(review.updates, sources)
    log(f"Usage check: {sum(u['total'] for u in usage)} uses found.")
    return client.review(
        files, usage=usage, fmt=fmt, source_url=source_url, wait=args.wait
    )


def _post(change: Change, review: Review, env: Mapping[str, str]) -> None:
    target = change.target
    if isinstance(target, GerritChange):
        user = _need(env, "GERRIT_HTTP_USER", "to the Gerrit account that posts")
        password = _need(env, "GERRIT_HTTP_PASSWORD", "to that account's HTTP password")
        link = next((u["url"] for u in review.updates if u.get("url")), None)
        gerrit.post(target, gerrit.fit(review.body, link), user, password)
        log("Posted the review on the Gerrit change.")
    elif isinstance(target, GitLabMergeRequest):
        token = _need(env, "GITLAB_TOKEN", "to a token with the api scope")
        done = gitlab.post(target, review.body, token)
        log(f"Review note {done} on the merge request.")


def failed(review: Review, fail_on: str) -> bool:
    """An update's verdict is ``fail_on`` or riskier."""
    if fail_on == "never":
        return False
    worst = VERDICTS.index(fail_on)
    return any(
        u.get("verdict") in VERDICTS and VERDICTS.index(u["verdict"]) <= worst
        for u in review.updates
    )


def log(message: str) -> None:
    print(f"depdelta: {message}", file=sys.stderr)


def run(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = parser().parse_args(argv)
    env = os.environ if env is None else env
    try:
        change = _change(args, env)
        base = change.base if change else args.base
        head = change.head if change else args.head
        for rev in (head, base):
            ensure_commit(args.repo, rev)
        files = changed_manifests(args.repo, base, head)
        if not files:
            log("The change touches no manifests or lockfiles: nothing to review.")
            return 0
        if len(files) > MAX_FILES:
            log(f"{len(files)} manifests changed; reviewing the first {MAX_FILES}.")
            files = files[:MAX_FILES]
        key = _need(env, "DEPDELTA_API_KEY", "to an API key from DepDelta Settings")
        api_url = args.api_url or env.get("DEPDELTA_API_URL") or DEFAULT_API_URL
        fmt = args.format or (
            "text" if change and change.platform == "gerrit" else "markdown"
        )
        source_url = change.source_url if change else None
        review = _review(DepDelta(key, api_url), args, files, fmt, source_url)
        log(f"{review.label} ({len(review.updates)} updates).")
        if change is None or args.print_only:
            print(review.body)
        else:
            _post(change, review, env)
    except (
        UsageError,
        EnvError,
        GitError,
        ApiError,
        gerrit.GerritError,
        gitlab.GitLabError,
        web.HttpError,
    ) as error:
        log(str(error))
        return 2
    return 1 if failed(review, args.fail_on) else 0


def main() -> None:  # pragma: no cover
    sys.exit(run())
