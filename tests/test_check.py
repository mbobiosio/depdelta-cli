# tests/test_check.py

from helpers import CLI_ENGINE, update

from depdelta_cli import check
from depdelta_cli.git import SourceFiles


def test_ecosystems_only_updates_with_symbols():
    maven = {**update([CLI_ENGINE]), "ecosystem": "maven"}

    assert check.ecosystems([update(), update([CLI_ENGINE]), maven]) == {
        "npm",
        "maven",
    }


def test_usage_success():
    sources = SourceFiles(
        [("src/a.ts", "import { CLIEngine } from 'eslint'\nnew CLIEngine()\n")], True
    )

    found = check.usage([update(), update([CLI_ENGINE])], sources)

    assert found == [
        {
            "ecosystem": "npm",
            "name": "eslint",
            "from_version": "8.57.0",
            "to_version": "9.0.0",
            "hits": [
                {
                    "path": "src/a.ts",
                    "line": 2,
                    "symbol": "CLIEngine",
                    "change": "removed",
                }
            ],
            "total": 1,
            "too_large": True,
        }
    ]


def test_usage_nothing_found():
    found = check.usage([update([CLI_ENGINE])], SourceFiles([], False))

    assert found[0]["hits"] == []
    assert found[0]["total"] == 0
