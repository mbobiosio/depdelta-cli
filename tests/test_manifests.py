# tests/test_manifests.py

import pytest

from depdelta_cli.manifests import is_manifest, skipped


@pytest.mark.parametrize(
    "path",
    [
        "package.json",
        "web/package-lock.json",
        "Cargo.toml",
        "requirements-dev.txt",
        "gradle/libs.versions.toml",
        "gradle/deps.versions.toml",
        "src/App/App.csproj",
        "Lib.fsproj",
        "Gemfile.lock",
    ],
)
def test_is_manifest_success(path):
    assert is_manifest(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/index.ts",
        "README.md",
        "node_modules/x/package.json",
        "vendor/pkg/composer.json",
        "a/build/pom.xml",
        "requirementsXtxt",
    ],
)
def test_is_manifest_rejects_others(path):
    assert not is_manifest(path)


def test_skipped_looks_only_at_directories():
    assert skipped("dist/a.js")
    assert not skipped("dist")
    assert not skipped("src/dist.js")
