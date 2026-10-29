# src/depdelta_cli/usage.py
#
# Where the checkout uses the declarations an update removes or changes.
# Copied from depdelta-api `app/updates/utils/usage.py` (the matching, not its
# tarball reading), so CI finds exactly what the GitHub App finds; change it
# there first, then copy it here. The code is read in CI and never sent: only
# the hits (path, line, symbol) go to DepDelta.
#
# Matching is a heuristic, per language:
#   TS/JS     files that import the package; what they import (named imports,
#             a default or namespace import, require) used as the removed or
#             changed declaration, or one of its members.
#   Java/Kt   files that can see the class (an import of it or of its
#             package, living in its package, or naming it fully qualified);
#             the class, its constructor or its members used (a getter read
#             as a Kotlin property included). Kotlin top-level functions and
#             properties (static members of a `FileKt` class) are matched by
#             their own name where Kotlin files import them.
#   Python    files that import the package's top-level module (`import x`,
#             `from x.sub import Y`); what they import used as the removed or
#             changed declaration, or reached through an imported module
#             (`x.sub.Y`), or one of its members.
# A file that imports a removed declaration but never uses it beyond the
# import still breaks the build: then the import line is the hit.

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

#: Hits kept per update (all of them are counted).
MAX_HITS = 50

UsageChange = Literal["removed", "changed"]

SOURCE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "npm": (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue"),
    "maven": (".java", ".kt", ".kts"),
    "pypi": (".py",),
}

#: Kinds naming a member of the declaration before the last dot (`get` and
#: `set` are TS accessors, `member` an enum member).
_MEMBER_KINDS = frozenset({"method", "property", "field", "get", "set", "member"})
_CONSTRUCTOR_KINDS = frozenset({"ctor", "constructor"})
#: Kinds with no name of their own to look for: call, construct and index
#: signatures, `export default x` (x's own line is diffed too).
_UNMATCHED_KINDS = frozenset({"call", "new", "index", "default"})
#: Member names too common to look for without their owner (`.name`, `.get(`).
_COMMON_MEMBERS = frozenset(
    {
        "apply",
        "bind",
        "call",
        "close",
        "data",
        "emit",
        "find",
        "init",
        "keys",
        "length",
        "name",
        "next",
        "open",
        "push",
        "read",
        "send",
        "size",
        "then",
        "toString",
        "type",
        "value",
        "values",
        "write",
    }
)
_NAME = re.compile(r"^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$")


@dataclass(frozen=True)
class ApiSymbol:
    """A declaration the update removes or changes."""

    kind: str
    #: Dotted name as declared: `CLIEngine`, `Linter.verify`.
    name: str
    #: The module (npm, PyPI) or Java package (Maven) it is declared in.
    module: str
    change: UsageChange

    @property
    def owner(self) -> str:
        """The top-level declaration: `Linter` for `Linter.verify`."""
        return self.name.split(".", 1)[0]

    @property
    def member(self) -> str | None:
        """The member a member kind names (`verify`), else None."""
        if self.kind in _MEMBER_KINDS and "." in self.name:
            return self.name.rsplit(".", 1)[1]
        return None


@dataclass(frozen=True)
class UsageHit:
    path: str
    line: int
    #: The symbol's dotted name.
    symbol: str
    change: UsageChange


@dataclass(frozen=True)
class UsageReport:
    """Where the checkout appears to use one update's removed or changed APIs."""

    #: The first MAX_HITS, by path and line.
    hits: tuple[UsageHit, ...] = ()
    total: int = 0


def _line_of(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def _span_lines(text: str, start: int, end: int) -> set[int]:
    return set(range(_line_of(text, start), _line_of(text, end) + 1))


def _word(name: str) -> str:
    """A regex for ``name`` as a whole identifier."""
    return rf"(?<![\w$]){re.escape(name)}(?![\w$])"


def _distinctive(member: str) -> bool:
    return len(member) >= 4 and member not in _COMMON_MEMBERS


def _hits(
    path: str,
    text: str,
    symbol: ApiSymbol,
    patterns: list[str],
    imports: set[int],
) -> Iterator[UsageHit]:
    """Lines of ``text`` matching any of ``patterns``; import lines only
    when nothing else matches."""
    lines: set[int] = set()
    for pattern in patterns:
        lines.update(_line_of(text, m.start()) for m in re.finditer(pattern, text))
    used = lines - imports
    for line in sorted(used or lines):
        yield UsageHit(path, line, symbol.name, symbol.change)


# ── TS/JS ────────────────────────────────────────────────────────────────────

_IMPORT = re.compile(
    r"""\bimport\s+(?:type\s+)?(?P<clause>[\w$*{}\s,]{1,2000}?)\s*from\s*"""
    r"""['"](?P<spec>[^'"\n]+)['"]"""
)
_REQUIRE = re.compile(
    r"""\b(?:const|let|var)\s+(?P<binding>\{[^}]{0,2000}\}|[\w$]+)\s*=\s*"""
    r"""require\(\s*['"](?P<spec>[^'"\n]+)['"]\s*\)"""
)


@dataclass
class _JsImports:
    #: Local name → the name it's exported as.
    named: dict[str, str]
    #: Locals bound to the whole module (default, `* as`, require).
    whole: set[str]
    #: Lines the import statements take.
    lines: set[int]


def _named(block: str, separator: str) -> dict[str, str]:
    """`{ a, b as c }` (import) or `{ a, b: c }` (require) → local → exported."""
    names: dict[str, str] = {}
    for part in block.strip("{} \n").split(","):
        part = part.strip().removeprefix("type ").strip()
        exported, _, local = part.partition(separator)
        exported, local = exported.strip(), local.strip() or exported.strip()
        if _NAME.match(exported) and _NAME.match(local):
            names[local] = exported
    return names


def _js_imports(text: str, package: str) -> _JsImports | None:
    """What a file imports from ``package`` (or a subpath); None for nothing."""

    def ours(spec: str) -> bool:
        return spec == package or spec.startswith(package + "/")

    found = _JsImports({}, set(), set())
    for match in _IMPORT.finditer(text):
        if not ours(match["spec"]):
            continue
        found.lines |= _span_lines(text, match.start(), match.end())
        clause = match["clause"]
        if braces := re.search(r"\{[^}]*\}", clause):
            found.named.update(_named(braces.group(0), " as "))
            clause = clause.replace(braces.group(0), "")
        for part in clause.split(","):
            part = part.strip()
            if part.startswith("*"):
                part = part.partition(" as ")[2].strip()
            if _NAME.match(part):
                found.whole.add(part)
    for match in _REQUIRE.finditer(text):
        if not ours(match["spec"]):
            continue
        found.lines |= _span_lines(text, match.start(), match.end())
        binding = match["binding"]
        if binding.startswith("{"):
            found.named.update(_named(binding, ":"))
        else:
            found.whole.add(binding)
    return found if found.lines else None


def _js_patterns(symbol: ApiSymbol, imports: _JsImports) -> list[str]:
    owner, member = symbol.owner, symbol.member
    dot = r"\s*\??\.\s*"
    # How the file names the owner: a named import, or a whole-module
    # binding's property (`ns.Linter`).
    names = [_word(local) for local, name in imports.named.items() if name == owner]
    names += [_word(local) + dot + _word(owner) for local in imports.whole]
    if member is None:
        if symbol.kind in _CONSTRUCTOR_KINDS:
            return [r"\bnew\s+" + name for name in names]
        return names
    patterns = [name + dot + _word(member) for name in names]
    # The default export may be the owner itself (`axios.create`).
    patterns += [_word(local) + dot + _word(member) for local in imports.whole]
    if names and _distinctive(member):
        # An instance of the owner: `linter.verifyAndFix`.
        patterns.append(r"\??\.\s*" + _word(member))
    return patterns


def _js_hits(
    files: list[tuple[str, str]], package: str, wanted: list[ApiSymbol]
) -> Iterator[UsageHit]:
    for path, text in files:
        imports = _js_imports(text, package)
        if imports is None:
            continue
        for symbol in wanted:
            yield from _hits(
                path, text, symbol, _js_patterns(symbol, imports), imports.lines
            )


# ── Java / Kotlin ────────────────────────────────────────────────────────────

_PACKAGE = re.compile(r"^[ \t]*package[ \t]+([\w.]+)", re.MULTILINE)
_JVM_IMPORT = re.compile(
    r"^[ \t]*import[ \t]+(?:static[ \t]+)?([\w.]+?)(\.\*)?(?:[ \t]+as[ \t]+(\w+))?"
    r"[ \t]*;?[ \t]*$",
    re.MULTILINE,
)


def _jvm_view(text: str, symbol: ApiSymbol) -> tuple[str, set[int]] | None:
    """The name ``symbol``'s class goes by in a file and the file's import
    lines, or None when the file can't see it."""
    owner = symbol.owner
    qualified = f"{symbol.module}.{owner}" if symbol.module else owner
    imports: set[int] = set()
    local: str | None = None
    for match in _JVM_IMPORT.finditer(text):
        target, wildcard, alias = match.groups()
        if wildcard and target == symbol.module:
            local = local or owner
        elif target == qualified:
            local = alias or owner
        elif target.startswith(qualified + ".") and not wildcard:
            # A nested class imported by itself: `CarProgressBar.Builder`.
            local = local or alias or target.rsplit(".", 1)[1]
        else:
            continue
        imports.add(_line_of(text, match.start()))
    if local is not None:
        return local, imports
    package = _PACKAGE.search(text)
    if (package.group(1) if package else "") == symbol.module or (
        symbol.module and re.search(_word(qualified), text)
    ):
        return owner, imports
    return None


def _getter_property(member: str) -> str | None:
    """Kotlin reads `getColor()` as `.color`."""
    if member.startswith("get") and len(member) > 3 and member[3].isupper():
        return member[3].lower() + member[4:]
    return None


def _jvm_patterns(symbol: ApiSymbol, local: str) -> list[str]:
    member = symbol.member
    if member is None:
        if symbol.kind in _CONSTRUCTOR_KINDS:
            return [_word(local) + r"\s*(?:<[^<>()]*>)?\s*\("]
        return [_word(local)]
    patterns = [_word(local) + r"\s*\.\s*" + _word(member)]
    if _distinctive(member):
        patterns.append(r"\.\s*" + _word(member))
        prop = _getter_property(member) if symbol.kind == "method" else None
        if prop is not None and _distinctive(prop):
            patterns.append(r"\.\s*" + _word(prop) + r"(?!\s*\()")
    return patterns


def _kotlin_top_level(
    text: str, symbol: ApiSymbol
) -> tuple[list[str], set[int]] | None:
    """Patterns for a Kotlin top-level function or property (compiled into a
    `FileKt` class Kotlin code never names) and the file's import lines, or
    None when the file can't see it.

    Kotlin imports these by their own name (`import p.transaction`); a
    wildcard import or the same package sees them too, and then only a
    distinctive name is looked for.
    """
    member = symbol.member
    assert member is not None
    names = {member}
    if (prop := _getter_property(member)) is not None:
        names.add(prop)
    found: set[str] = set()
    imports: set[int] = set()
    wildcard = False
    for match in _JVM_IMPORT.finditer(text):
        target, star, alias = match.groups()
        package, _, name = target.rpartition(".")
        if star and target == symbol.module:
            wildcard = True
        elif not star and package == symbol.module and name in names:
            found.add(alias or name)
        else:
            continue
        imports.add(_line_of(text, match.start()))
    if not found:
        same = _PACKAGE.search(text)
        if wildcard or (same.group(1) if same else "") == symbol.module:
            found = {name for name in names if _distinctive(name)}
    if not found:
        return None
    return [_word(name) for name in sorted(found)], imports


def _jvm_hits(
    files: list[tuple[str, str]], wanted: list[ApiSymbol]
) -> Iterator[UsageHit]:
    for path, text in files:
        kotlin = path.endswith((".kt", ".kts"))
        for symbol in wanted:
            if kotlin and symbol.owner.endswith("Kt") and symbol.member is not None:
                seen = _kotlin_top_level(text, symbol)
                if seen is not None:
                    yield from _hits(path, text, symbol, *seen)
                continue
            view = _jvm_view(text, symbol)
            if view is None:
                continue
            local, imports = view
            yield from _hits(path, text, symbol, _jvm_patterns(symbol, local), imports)


# ── Python ───────────────────────────────────────────────────────────────────

_PY_FROM = re.compile(
    r"^[ \t]*from[ \t]+(?P<module>[\w.]+)[ \t]+import[ \t]+"
    r"(?P<names>\([^)]*\)|[^\n#;]*)",
    re.MULTILINE,
)
_PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+(?P<names>[^\n#;]+)", re.MULTILINE)
#: Attributes between a module binding and the name (`x.sub.Y`).
_PY_CHAIN = r"(?:\s*\.\s*[A-Za-z_]\w*)*?\s*\.\s*"


@dataclass
class _PyImports:
    #: Local name → the name it's imported as.
    named: dict[str, str]
    #: Locals that may be bound to one of the package's modules.
    modules: set[str]
    #: `from x import *`: every name is visible as itself.
    star: bool
    #: Lines the import statements take.
    lines: set[int]


def _py_imports(text: str, top: str) -> _PyImports | None:
    """What a file imports from the package whose top-level module is
    ``top``; None for nothing."""
    found = _PyImports({}, set(), False, set())
    for match in _PY_FROM.finditer(text):
        if match["module"].split(".")[0] != top:
            continue
        found.lines |= _span_lines(text, match.start(), match.end())
        for part in match["names"].strip("()").split(","):
            name, _, alias = part.strip().partition(" as ")
            name, local = name.strip(), alias.strip() or name.strip()
            if name == "*":
                found.star = True
            elif name.isidentifier() and local.isidentifier():
                found.named[local] = name
                # `from x import sub`: sub may be a module.
                found.modules.add(local)
    for match in _PY_IMPORT.finditer(text):
        for part in match["names"].split(","):
            name, _, alias = part.strip().partition(" as ")
            if name.strip().split(".")[0] != top:
                continue
            found.lines |= _span_lines(text, match.start(), match.end())
            found.modules.add(alias.strip() or top)
    return found if found.lines else None


def _py_patterns(symbol: ApiSymbol, imports: _PyImports) -> list[str]:
    owner, member = symbol.owner, symbol.member
    names = [_word(local) for local, name in imports.named.items() if name == owner]
    if imports.star:
        names.append(_word(owner))
    names += [_word(local) + _PY_CHAIN + _word(owner) for local in imports.modules]
    if member is None:
        if symbol.kind in _CONSTRUCTOR_KINDS:
            return [name + r"\s*\(" for name in names]
        return names
    patterns = [name + r"\s*\.\s*" + _word(member) for name in names]
    if names and _distinctive(member):
        # An instance of the owner: `session.mount`.
        patterns.append(r"\.\s*" + _word(member))
    return patterns


def _py_hits(
    files: list[tuple[str, str]], wanted: list[ApiSymbol]
) -> Iterator[UsageHit]:
    by_top: dict[str, list[ApiSymbol]] = {}
    for symbol in wanted:
        by_top.setdefault(symbol.module.split(".")[0], []).append(symbol)
    for path, text in files:
        for top, symbols in by_top.items():
            imports = _py_imports(text, top)
            if imports is None:
                continue
            for symbol in symbols:
                patterns = _py_patterns(symbol, imports)
                yield from _hits(path, text, symbol, patterns, imports.lines)


def find_usages(
    ecosystem: str,
    package: str,
    wanted: list[ApiSymbol],
    files: list[tuple[str, str]],
) -> UsageReport:
    """Where ``files`` appear to use ``wanted`` declarations of ``package``.

    Args:
        ecosystem: "npm", "maven" or "pypi" (no other has an API diff).
        package: The package's name (npm files import it by name; Python
            files by its module's, which the symbols carry).
        wanted: The update's removed and changed declarations.
        files: (path, text) of the repository's source files.
    """
    extensions = SOURCE_EXTENSIONS.get(ecosystem, ())
    mine = [(p, t) for p, t in files if extensions and p.endswith(extensions)]
    if not wanted or not mine:
        return UsageReport()
    if ecosystem == "npm":
        found = _js_hits(mine, package, wanted)
    elif ecosystem == "pypi":
        found = _py_hits(mine, wanted)
    else:
        found = _jvm_hits(mine, wanted)
    hits = sorted(set(found), key=lambda h: (h.path, h.line, h.symbol))
    return UsageReport(tuple(hits[:MAX_HITS]), len(hits))
