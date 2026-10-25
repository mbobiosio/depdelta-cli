# src/depdelta_cli/check.py
#
# The usage check: for each update with removed or changed declarations,
# where this checkout uses them. Runs in CI on CI's copy of the code; only
# the hits (path, line, symbol) are sent back.

from depdelta_cli.git import SourceFiles
from depdelta_cli.usage import ApiSymbol, find_usages


def ecosystems(updates: list[dict]) -> set[str]:
    """Ecosystems of the updates that have declarations to look for."""
    return {u["ecosystem"] for u in updates if u.get("symbols")}


def usage(updates: list[dict], sources: SourceFiles) -> list[dict]:
    """CiUsage for each update with symbols, as POST /ci/reviews takes it."""
    found: list[dict] = []
    for update in updates:
        if not update.get("symbols"):
            continue
        wanted = [
            ApiSymbol(
                kind=s["kind"], name=s["name"], module=s["module"], change=s["change"]
            )
            for s in update["symbols"]
        ]
        report = find_usages(update["ecosystem"], update["name"], wanted, sources.files)
        found.append(
            {
                "ecosystem": update["ecosystem"],
                "name": update["name"],
                "from_version": update["from_version"],
                "to_version": update["to_version"],
                "hits": [
                    {
                        "path": h.path,
                        "line": h.line,
                        "symbol": h.symbol,
                        "change": h.change,
                    }
                    for h in report.hits
                ],
                "total": report.total,
                "too_large": sources.too_large,
            }
        )
    return found
