# tests/helpers.py

from depdelta_cli import web


class FakeWeb:
    """Stands in for web.request: answers in turn, records what was sent."""

    def __init__(self, *replies: web.Response | Exception):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def __call__(self, method, url, *, body=None, headers=None) -> web.Response:
        self.calls.append(
            {"method": method, "url": url, "body": body, "headers": headers or {}}
        )
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def ok(data: object, status: int = 200) -> web.Response:
    return web.Response(status, data)


def review(
    status: str = "ready",
    updates: list[dict] | None = None,
    retry_after: int | None = None,
    body: str = "### DepDelta review",
) -> web.Response:
    return ok(
        {
            "data": {
                "status": status,
                "label": "🔴 Breaking",
                "body": body,
                "retry_after": retry_after,
                "verdict": "breaking",
                "updates": updates or [],
            }
        }
    )


def update(symbols: list[dict] | None = None, verdict: str = "breaking") -> dict:
    return {
        "ecosystem": "npm",
        "name": "eslint",
        "from_version": "8.57.0",
        "to_version": "9.0.0",
        "verdict": verdict,
        "label": "🔴 Breaking",
        "url": "https://depdelta.com/npm/eslint/8.57.0...9.0.0",
        "problem": None,
        "indexing": False,
        "symbols": symbols or [],
    }


CLI_ENGINE = {
    "kind": "class",
    "name": "CLIEngine",
    "module": "lib/api",
    "change": "removed",
}
