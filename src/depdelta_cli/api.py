# src/depdelta_cli/api.py
#
# DepDelta's POST /ci/reviews: the change's manifests in, the review out.
# While release notes are read the review says `indexing`; it is asked again
# after `retry_after` seconds until it is ready or the wait runs out.

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from depdelta_cli import web
from depdelta_cli.git import ChangedFile

DEFAULT_API_URL = "https://api.depdelta.com/api/v1"
#: Server errors and network failures are tried this many times in all.
ATTEMPTS = 3
RETRY_SECONDS = 5
#: When the API gives no retry_after.
POLL_SECONDS = 15


class ApiError(Exception):
    """DepDelta refused the review (bad key, spent budget, bad request)."""


@dataclass(frozen=True)
class Review:
    status: str
    label: str
    body: str
    retry_after: int | None
    verdict: str | None
    updates: list[dict]
    #: `.depdelta.yml` sets install_scripts: block and something is flagged.
    blocked: bool = False
    #: What was wrong with `.depdelta.yml`, one line each.
    notes: tuple[str, ...] = ()


def _message(body: object) -> str:
    """The error envelope's message: `{"detail": {"message": …}}`, a bare
    envelope, or FastAPI's validation list."""
    if isinstance(body, dict):
        detail = body.get("detail", body)
        if isinstance(detail, dict) and detail.get("message"):
            return str(detail["message"])
        if isinstance(detail, list) and detail and isinstance(detail[0], dict):
            first = detail[0]
            where = ".".join(str(p) for p in first.get("loc", ()))
            return f"{where}: {first.get('msg', 'invalid')}"
        if isinstance(detail, str):
            return detail
    if isinstance(body, str) and body:
        return body[:300]
    return "no details"


def _review(data: dict) -> Review:
    return Review(
        status=str(data["status"]),
        label=str(data["label"]),
        body=str(data["body"]),
        retry_after=data.get("retry_after"),
        verdict=data.get("verdict"),
        updates=list(data.get("updates") or []),
        blocked=data.get("blocked") is True,
        notes=tuple(str(n) for n in data.get("notes") or ()),
    )


class DepDelta:
    def __init__(
        self,
        key: str,
        api_url: str = DEFAULT_API_URL,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.key = key
        self.url = f"{api_url.rstrip('/')}/ci/reviews"
        self.sleep = sleep
        self.clock = clock

    def ask(
        self,
        files: list[ChangedFile],
        *,
        usage: list[dict] | None = None,
        fmt: str = "markdown",
        source_url: str | None = None,
        config: str | None = None,
    ) -> Review:
        """One ask; server errors and network failures are tried again."""
        payload: dict = {
            "files": [{"path": f.path, "base": f.base, "head": f.head} for f in files],
            "usage": usage or [],
            "format": fmt,
        }
        if source_url:
            # A link with {path} and {line} (Bitbucket, Azure DevOps), or the
            # files' page that `/<path>#L<line>` is added to.
            key = "source_link" if "{path}" in source_url else "source_url"
            payload[key] = source_url
        if config is not None:
            payload["config"] = config
        for attempt in range(1, ATTEMPTS + 1):
            try:
                reply = web.request(
                    "POST",
                    self.url,
                    body=payload,
                    headers={
                        "Authorization": f"Bearer {self.key}",
                        # New for every ask: a repeat must see fresh notes.
                        "Idempotency-Key": str(uuid.uuid4()),
                    },
                )
            except web.HttpError as error:
                if attempt == ATTEMPTS:
                    raise ApiError(str(error)) from error
                self.sleep(RETRY_SECONDS * attempt)
                continue
            if reply.status >= 500 and attempt < ATTEMPTS:
                self.sleep(RETRY_SECONDS * attempt)
                continue
            if reply.status != 200 or not isinstance(reply.body, dict):
                raise ApiError(
                    f"DepDelta answered {reply.status}: {_message(reply.body)}"
                )
            return _review(reply.body["data"])
        raise AssertionError("unreachable")  # pragma: no cover

    def review(
        self,
        files: list[ChangedFile],
        *,
        usage: list[dict] | None = None,
        fmt: str = "markdown",
        source_url: str | None = None,
        config: str | None = None,
        wait: float = 300,
    ) -> Review:
        """Ask until the review is ready or ``wait`` seconds pass; then the
        last answer (still `indexing`) is the review."""
        deadline = self.clock() + wait
        while True:
            review = self.ask(
                files, usage=usage, fmt=fmt, source_url=source_url, config=config
            )
            if review.status != "indexing":
                return review
            pause = review.retry_after or POLL_SECONDS
            if self.clock() + pause > deadline:
                return review
            self.sleep(pause)
