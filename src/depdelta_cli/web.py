# src/depdelta_cli/web.py
#
# JSON over HTTPS with the standard library, so the command needs nothing
# installed beyond Python and git.

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from depdelta_cli import __version__

USER_AGENT = f"depdelta-cli/{__version__}"
TIMEOUT_SECONDS = 60


@dataclass
class Response:
    status: int
    body: object
    headers: dict[str, str] = field(default_factory=dict)


class HttpError(Exception):
    """The server couldn't be reached."""


def _decode(raw: bytes) -> object:
    text = raw.decode("utf-8", "replace")
    # Gerrit prefixes JSON with )]}' against XSSI.
    text = text.removeprefix(")]}'").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def request(
    method: str,
    url: str,
    *,
    body: object = None,
    headers: dict[str, str] | None = None,
) -> Response:
    """Send ``body`` as JSON; any status comes back (only a network failure
    raises)."""
    data = None if body is None else json.dumps(body).encode()
    sent = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if data is not None:
        sent["Content-Type"] = "application/json"
    sent.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=sent, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as reply:
            return Response(reply.status, _decode(reply.read()), dict(reply.headers))
    except urllib.error.HTTPError as error:
        return Response(error.code, _decode(error.read()), dict(error.headers))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise HttpError(f"{method} {url}: {error}") from error


def basic(user: str, password: str) -> str:
    """An HTTP basic Authorization value."""
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"
