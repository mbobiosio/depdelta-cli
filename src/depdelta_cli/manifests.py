# src/depdelta_cli/manifests.py
#
# Which changed files are manifests and lockfiles: only those are sent to
# DepDelta, never source code. The names follow depdelta-api
# (`app/reports/utils/manifests.py` and `app/github/utils/repos.py`); change
# them there first, then here.

import re

#: Supported manifests and lockfiles, by lower-cased file name.
MANIFEST_NAMES = frozenset(
    {
        "build.gradle",
        "build.gradle.kts",
        "cargo.lock",
        "cargo.toml",
        "composer.json",
        "composer.lock",
        "directory.packages.props",
        "gemfile",
        "gemfile.lock",
        "gems.locked",
        "gems.rb",
        "go.mod",
        "go.sum",
        # Gradle dependency locking.
        "gradle.lockfile",
        "buildscript-gradle.lockfile",
        "settings-gradle.lockfile",
        "libs.versions.toml",
        "npm-shrinkwrap.json",
        "package-lock.json",
        "package.json",
        "packages.config",
        "packages.lock.json",
        "pipfile.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "pom.xml",
        "pubspec.lock",
        "pubspec.yaml",
        "pyproject.toml",
        "requirements.txt",
        # pluginManagement { plugins { … } }: plugin versions.
        "settings.gradle",
        "settings.gradle.kts",
        "uv.lock",
        "yarn.lock",
    }
)
#: requirements-dev.txt, requirements.in.txt …
_REQUIREMENTS = re.compile(r"^requirements[\w.-]*\.txt$")
#: MSBuild project files: C# (MyApp.csproj), F# and Visual Basic.
_MSBUILD_PROJECT = re.compile(r"^.+\.(?:cs|fs|vb)proj$")

#: Vendored, generated and build directories: never read.
SKIP_DIRS = frozenset(
    {
        ".bundle",
        ".dart_tool",
        ".git",
        ".gradle",
        ".next",
        ".nuxt",
        ".venv",
        "__fixtures__",
        "__pycache__",
        "bin",
        "bower_components",
        "build",
        "dist",
        "fixtures",
        "node_modules",
        "obj",
        "out",
        "site-packages",
        "target",
        "testdata",
        "vendor",
        "venv",
    }
)


def skipped(path: str) -> bool:
    """Inside a vendored, generated or build directory."""
    return any(part in SKIP_DIRS for part in path.split("/")[:-1])


def is_manifest(path: str) -> bool:
    """A supported manifest or lockfile outside vendored and build folders."""
    if skipped(path):
        return False
    base = path.rsplit("/", 1)[-1].lower()
    return (
        base in MANIFEST_NAMES
        or bool(_REQUIREMENTS.match(base))
        # gradle/libs.versions.toml variants: deps.versions.toml
        or base.endswith(".versions.toml")
        or bool(_MSBUILD_PROJECT.match(base))
    )
