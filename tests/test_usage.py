# tests/test_usage.py
#
# The matcher's tests, as depdelta-api's (tests/unit/updates/test_usage.py)
# for the same code.

import pytest

from depdelta_cli import usage as module
from depdelta_cli.usage import (
    ApiSymbol,
    UsageHit,
    UsageReport,
    find_usages,
    go_package_name,
)


def _hits(report: UsageReport) -> list[tuple[str, int, str]]:
    return [(h.path, h.line, h.symbol) for h in report.hits]


def test_symbol_owner_and_member():
    method = ApiSymbol("method", "CarProgressBar.Builder.setColor", "p", "removed")
    assert (method.owner, method.member) == ("CarProgressBar", "setColor")
    const = ApiSymbol("const", "N.Deep.k", "a", "removed")
    assert (const.owner, const.member) == ("N", None)
    lone = ApiSymbol("method", "f", "a", "removed")
    assert lone.member is None


ESLINT = [
    ApiSymbol("class", "CLIEngine", "lib/api", "removed"),
    ApiSymbol("method", "Linter.verifyAndFix", "lib/api", "changed"),
    ApiSymbol("constructor", "Linter", "lib/api", "changed"),
    ApiSymbol("function", "oldThing", "lib/api", "removed"),
]


def test_find_usages_named_imports():
    text = (
        "import { CLIEngine, Linter as L } from 'eslint'\n"
        "const engine = new CLIEngine()\n"
        "const linter = new L({})\n"
        "linter.verifyAndFix('x')\n"
        "L.verifyAndFix('y')\n"
    )

    report = find_usages("npm", "eslint", ESLINT, [("src/a.ts", text)])

    assert _hits(report) == [
        ("src/a.ts", 2, "CLIEngine"),
        ("src/a.ts", 3, "Linter"),
        ("src/a.ts", 4, "Linter.verifyAndFix"),
        ("src/a.ts", 5, "Linter.verifyAndFix"),
    ]
    assert report.total == 4
    assert report.hits[0] == UsageHit("src/a.ts", 2, "CLIEngine", "removed")


def test_find_usages_import_line_when_never_used():
    text = "import {\n  oldThing,\n} from 'eslint/use-at-your-own-risk'\n"

    report = find_usages("npm", "eslint", ESLINT, [("src/c.ts", text)])

    # Importing a removed export breaks the build by itself.
    assert _hits(report) == [("src/c.ts", 2, "oldThing")]


def test_find_usages_whole_module():
    text = (
        "import eslint, * as ns from 'eslint'\n"
        "const api = require('eslint')\n"
        "eslint.CLIEngine.version\n"
        "new ns.Linter()\n"
        "api.verifyAndFix()\n"
    )

    report = find_usages("npm", "eslint", ESLINT, [("src/b.js", text)])

    assert _hits(report) == [
        ("src/b.js", 3, "CLIEngine"),
        ("src/b.js", 4, "Linter"),
        ("src/b.js", 5, "Linter.verifyAndFix"),
    ]


def test_find_usages_destructured_require():
    text = (
        "const { CLIEngine: Engine, Linter } = require('eslint')\n"
        "new Engine()\n"
        "new Linter()\n"
    )

    report = find_usages("npm", "eslint", ESLINT, [("a.cjs", text)])

    assert _hits(report) == [("a.cjs", 2, "CLIEngine"), ("a.cjs", 3, "Linter")]


def test_find_usages_common_member_needs_its_owner():
    wanted = [ApiSymbol("method", "Linter.name", "a", "removed")]
    text = "import { Linter } from 'eslint'\nuser.name\nLinter.name\n"

    report = find_usages("npm", "eslint", wanted, [("a.ts", text)])

    assert _hits(report) == [("a.ts", 3, "Linter.name")]


def test_find_usages_other_packages_ignored():
    files = [
        ("a.ts", "import { oldThing } from 'eslint-plugin-x'\noldThing()\n"),
        ("b.ts", "const { oldThing } = require('eslint-x')\noldThing()\n"),
        ("c.py", "import eslint\n"),
    ]

    assert find_usages("npm", "eslint", ESLINT, files) == UsageReport()


def test_find_usages_nothing_wanted():
    files = [("a.ts", "import { x } from 'eslint'\n")]

    assert find_usages("npm", "eslint", [], files) == UsageReport()


def test_find_usages_no_source_for_the_ecosystem():
    wanted = [ApiSymbol("class", "C", "a", "removed")]

    assert find_usages("pypi", "x", wanted, [("a.ts", "C")]) == UsageReport()


def test_find_usages_caps_the_hits(monkeypatch):
    monkeypatch.setattr(module, "MAX_HITS", 2)
    text = "import { oldThing } from 'eslint'\n" + "oldThing()\n" * 5

    report = find_usages("npm", "eslint", ESLINT, [("a.ts", text)])

    assert _hits(report) == [("a.ts", 2, "oldThing"), ("a.ts", 3, "oldThing")]
    assert report.total == 5


CAR = [
    ApiSymbol(
        "method", "CarProgressBar.Builder.getColor", "androidx.car.app.model", "removed"
    ),
    ApiSymbol("ctor", "CarProgressBar", "androidx.car.app.model", "changed"),
    ApiSymbol("class", "Gone", "androidx.car.app.model", "removed"),
    ApiSymbol("field", "CarProgressBar.name", "androidx.car.app.model", "removed"),
]


def test_find_usages_kotlin_imports():
    text = (
        "package app\n"
        "import androidx.car.app.model.CarProgressBar\n"
        "import androidx.car.app.model.Gone as G\n"
        'val bar = CarProgressBar("a", 1)\n'
        "val color = builder.color\n"
        "val g = G()\n"
        "val n = CarProgressBar.name\n"
        "val other = user.name\n"
    )

    report = find_usages("maven", "androidx.car.app:app", CAR, [("X.kt", text)])

    assert _hits(report) == [
        ("X.kt", 4, "CarProgressBar"),
        ("X.kt", 5, "CarProgressBar.Builder.getColor"),
        ("X.kt", 6, "Gone"),
        ("X.kt", 7, "CarProgressBar.name"),
    ]


def test_find_usages_java_wildcard_import():
    text = (
        "package app;\n"
        "import androidx.car.app.model.*;\n"
        'class Y { void f() { b.getColor(); new CarProgressBar<T>("a", 1); } }\n'
    )

    report = find_usages("maven", "x", CAR, [("Y.java", text)])

    assert _hits(report) == [
        ("Y.java", 3, "CarProgressBar"),
        ("Y.java", 3, "CarProgressBar.Builder.getColor"),
    ]


def test_find_usages_java_nested_class_import():
    text = (
        "import androidx.car.app.model.CarProgressBar.Builder;\n"
        "class Y { void f() { new Builder().getColor(); } }\n"
    )

    report = find_usages("maven", "x", CAR[:1], [("Y.java", text)])

    assert _hits(report) == [("Y.java", 2, "CarProgressBar.Builder.getColor")]


def test_find_usages_jvm_same_package_and_qualified():
    same = "package androidx.car.app.model;\nclass A { Gone g; }\n"
    qualified = "class B { androidx.car.app.model.Gone g; }\n"

    report = find_usages(
        "maven", "x", [CAR[2]], [("A.java", same), ("B.java", qualified)]
    )

    assert _hits(report) == [("A.java", 2, "Gone"), ("B.java", 1, "Gone")]


def test_find_usages_jvm_import_line_when_never_used():
    text = "import androidx.car.app.model.Gone\nclass A\n"

    report = find_usages("maven", "x", [CAR[2]], [("A.kt", text)])

    assert _hits(report) == [("A.kt", 1, "Gone")]


def test_find_usages_jvm_file_that_cant_see_the_class():
    text = "package app\nimport other.Gone\nval g = Gone()\nb.getColor()\n"

    assert find_usages("maven", "x", CAR, [("A.kt", text)]) == UsageReport()


def test_find_usages_jvm_default_package():
    wanted = [ApiSymbol("class", "Top", "", "removed")]

    report = find_usages("maven", "x", wanted, [("A.java", "class A { Top t; }\n")])

    assert _hits(report) == [("A.java", 1, "Top")]


def test_find_usages_short_property_of_a_getter_not_looked_for():
    # Kotlin reads `getUrl()` as `.url`: too short a name to look for alone.
    wanted = [ApiSymbol("method", "Link.getUrl", "p", "removed")]
    text = "import p.Link\nval a = link.url\nval b = link.getUrl()\n"

    report = find_usages("maven", "x", wanted, [("A.kt", text)])

    assert _hits(report) == [("A.kt", 3, "Link.getUrl")]


def test_find_usages_jvm_method():
    wanted = [ApiSymbol("method", "Link.toggle", "p", "changed")]
    text = "import p.Link\nlink.toggle()\n"

    report = find_usages("maven", "x", wanted, [("A.kt", text)])

    assert _hits(report) == [("A.kt", 2, "Link.toggle")]


TX = "org.jetbrains.exposed.sql.transactions"


TOP = [
    ApiSymbol("method", "ThreadLocalTransactionManagerKt.transaction", TX, "changed"),
    ApiSymbol("method", "ConfigKt.getDefaultIsolation", TX, "removed"),
    ApiSymbol("method", "QueriesKt.select", TX, "removed"),
]


def test_find_usages_kotlin_top_level_imported_by_name():
    text = (
        "import org.jetbrains.exposed.sql.transactions.transaction\n"
        "import org.jetbrains.exposed.sql.transactions.defaultIsolation as iso\n"
        "fun a() = transaction {\n"
        "  println(iso)\n"
        "}\n"
        "fun b() = query.select { }\n"
    )

    report = find_usages("maven", "x", TOP, [("A.kt", text)])

    assert _hits(report) == [
        ("A.kt", 3, "ThreadLocalTransactionManagerKt.transaction"),
        ("A.kt", 4, "ConfigKt.getDefaultIsolation"),
    ]


def test_find_usages_kotlin_top_level_wildcard_or_same_package():
    wildcard = f"import {TX}.*\nfun a() = transaction {{ }}\nq.select {{ }}\n"
    same = f"package {TX}\nval d = defaultIsolation\n"

    report = find_usages("maven", "x", TOP, [("A.kt", wildcard), ("B.kt", same)])

    # `select` is distinctive enough; seen only through the wildcard.
    assert _hits(report) == [
        ("A.kt", 2, "ThreadLocalTransactionManagerKt.transaction"),
        ("A.kt", 3, "QueriesKt.select"),
        ("B.kt", 2, "ConfigKt.getDefaultIsolation"),
    ]


def test_find_usages_kotlin_top_level_short_name_needs_its_import():
    wanted = [ApiSymbol("method", "OpsKt.eq", TX, "removed")]
    seen = f"import {TX}.*\nval x = a eq b\n"
    imported = f"import {TX}.eq\nval x = a eq b\n"

    report = find_usages("maven", "x", wanted, [("A.kt", seen), ("B.kt", imported)])

    assert _hits(report) == [("B.kt", 2, "OpsKt.eq")]


def test_find_usages_kotlin_top_level_not_visible():
    text = "import other.transaction\nfun a() = transaction { }\n"

    assert find_usages("maven", "x", TOP, [("A.kt", text)]) == UsageReport()


def test_find_usages_java_calls_the_kt_class():
    text = (
        f"import {TX}.ThreadLocalTransactionManagerKt;\n"
        "ThreadLocalTransactionManagerKt.transaction(db, s);\n"
    )

    report = find_usages("maven", "x", TOP[:1], [("A.java", text)])

    assert _hits(report) == [
        ("A.java", 2, "ThreadLocalTransactionManagerKt.transaction")
    ]


REQUESTS = [
    ApiSymbol("method", "Session.get_adapter", "requests.sessions", "removed"),
    ApiSymbol("class", "HTTPAdapter", "requests.adapters", "changed"),
    ApiSymbol("export", "Timeout", "requests", "removed"),
    ApiSymbol("constructor", "Session", "requests.sessions", "changed"),
    ApiSymbol("function", "dump", "yaml", "removed"),
]


def test_find_usages_python_success():
    text = (
        "import requests\n"
        "import os, requests.adapters as ra\n"
        "from requests import Session as S, adapters\n"
        "from requests.exceptions import (\n"
        "    Timeout,\n"
        ")\n"
        "from .local import Thing\n"
        "s = S()\n"
        "s.get_adapter('x')\n"
        "adapters.HTTPAdapter()\n"
        "ra.HTTPAdapter()\n"
        "requests.sessions.Session().close()\n"
        "except Timeout:\n"
    )

    report = find_usages("pypi", "requests", REQUESTS, [("app/client.py", text)])

    assert _hits(report) == [
        ("app/client.py", 8, "Session"),
        ("app/client.py", 9, "Session.get_adapter"),
        ("app/client.py", 10, "HTTPAdapter"),
        ("app/client.py", 11, "HTTPAdapter"),
        ("app/client.py", 12, "Session"),
        ("app/client.py", 13, "Timeout"),
    ]


def test_find_usages_python_star_import():
    text = "from yaml import *\ndump({})\n"

    report = find_usages("pypi", "pyyaml", REQUESTS, [("tool.py", text)])

    assert _hits(report) == [("tool.py", 2, "dump")]


def test_find_usages_python_import_line_when_never_used():
    text = "from yaml import dump, 3bad, x as 4y\n"

    report = find_usages("pypi", "pyyaml", REQUESTS, [("tool.py", text)])

    assert _hits(report) == [("tool.py", 1, "dump")]


def test_find_usages_python_common_member_needs_its_owner():
    wanted = [ApiSymbol("method", "Session.get", "requests.sessions", "changed")]
    text = "from requests import Session\ns = Session()\ns.get(1)\nSession.get(s, 1)\n"

    report = find_usages("pypi", "requests", wanted, [("tool.py", text)])

    assert _hits(report) == [("tool.py", 4, "Session.get")]


def test_find_usages_python_other_packages_ignored():
    text = "import os\nfrom json import dump\ndump({})\n"

    report = find_usages("pypi", "pyyaml", REQUESTS, [("tool.py", text)])

    assert report.total == 0


REDIS = "github.com/redis/go-redis/v9"
GO = [
    ApiSymbol("method", "Client.Pipelined", REDIS, "changed"),
    ApiSymbol("func", "NewClient", REDIS, "changed"),
    ApiSymbol("type", "Options", REDIS, "removed"),
    ApiSymbol("field", "Options.Dialer", REDIS, "removed"),
    ApiSymbol("method", "Cmd.Err", REDIS, "changed"),
    ApiSymbol("type", "Node", "gopkg.in/yaml.v3", "changed"),
]


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("github.com/redis/go-redis/v9", "redis"),
        ("gopkg.in/yaml.v3", "yaml"),
        ("github.com/hashicorp/golang-lru", "lru"),
        ("github.com/nats-io/nats.go", "nats"),
        ("github.com/segmentio/kafka-go", "kafka"),
        ("github.com/go-chi/chi/v5/middleware", "middleware"),
        ("github.com/spf13/cobra-cli", "cli"),
        ("example.com", "example.com"),
    ],
)
def test_go_package_name_success(path, name):
    assert go_package_name(path) == name


def test_find_usages_go_success():
    text = (
        "package app\n"
        "\n"
        "import (\n"
        '\t"context"\n'
        '\t"github.com/redis/go-redis/v9"\n'
        '\ty "gopkg.in/yaml.v3"\n'
        ")\n"
        "\n"
        "func run(ctx context.Context) {\n"
        "\tc := redis.NewClient(&redis.Options{})\n"
        "\tc.Pipelined(ctx, nil)\n"
        "\tvar n y.Node\n"
        '\t_ = redis.Options{Addr: "x"}.Dialer\n'
        "\tc.Ping(ctx).Err()\n"
        "}\n"
    )

    report = find_usages("go", REDIS, GO, [("app/run.go", text)])

    assert _hits(report) == [
        ("app/run.go", 10, "NewClient"),
        ("app/run.go", 10, "Options"),
        ("app/run.go", 11, "Client.Pipelined"),
        ("app/run.go", 12, "Node"),
        ("app/run.go", 13, "Options"),
        ("app/run.go", 13, "Options.Dialer"),
    ]


def test_find_usages_go_single_alias_and_dot_imports():
    text = (
        'import r "github.com/redis/go-redis/v9"\n'
        'import . "gopkg.in/yaml.v3"\n'
        "var o = r.Options{}\n"
        "var n Node\n"
    )

    report = find_usages("go", REDIS, GO, [("main.go", text)])

    assert _hits(report) == [("main.go", 3, "Options"), ("main.go", 4, "Node")]


def test_find_usages_go_blank_import_and_import_line_ignored():
    text = (
        'import _ "github.com/redis/go-redis/v9"\n'
        'import "gopkg.in/yaml.v3"\n'
        "var x = 1\n"
    )

    report = find_usages("go", REDIS, GO, [("main.go", text)])

    # A blank import uses nothing; a package imported but unused uses
    # nothing either (and doesn't compile).
    assert report.total == 0


def test_find_usages_go_other_packages_ignored():
    text = 'import "github.com/other/redis"\nvar o = redis.Options{}\n'

    report = find_usages("go", REDIS, GO, [("main.go", text)])

    assert report.total == 0


MONOLOG = [
    ApiSymbol("method", "Logger.pushHandler", "Monolog", "changed"),
    ApiSymbol("constructor", "StreamHandler", "Monolog\\Handler", "changed"),
    ApiSymbol("member", "Level.Debug", "Monolog", "removed"),
    ApiSymbol("const", "Logger.DEBUG", "Monolog", "removed"),
    ApiSymbol("property", "Logger.timezone", "Monolog", "removed"),
    ApiSymbol("class", "Utils", "Monolog", "removed"),
    ApiSymbol("function", "jsonEncode", "Monolog\\Utils", "removed"),
    ApiSymbol("const", "VERSION", "Monolog", "removed"),
]


def test_find_usages_php_success():
    text = (
        "<?php\n"
        "namespace App;\n"
        "\n"
        "use Monolog\\{Logger, Level as L, function Utils\\nope};\n"
        "use Monolog\\Handler;\n"
        "use function Monolog\\Utils\\jsonEncode;\n"
        "use const Monolog\\VERSION, Bad Name;\n"
        "\n"
        "$log = new Logger('x');\n"
        "$log->pushHandler(new Handler\\StreamHandler('php://stderr'));\n"
        "$l = L::Debug;\n"
        "$x = Logger::DEBUG;\n"
        "echo \\Monolog\\Utils::class;\n"
        "jsonEncode([]);\n"
        "echo VERSION, Logger::$timezone;\n"
        "$other?->pushHandler(1);\n"
    )

    report = find_usages("composer", "monolog/monolog", MONOLOG, [("src/a.php", text)])

    assert _hits(report) == [
        ("src/a.php", 10, "Logger.pushHandler"),
        ("src/a.php", 10, "StreamHandler"),
        ("src/a.php", 11, "Level.Debug"),
        ("src/a.php", 12, "Logger.DEBUG"),
        ("src/a.php", 13, "Utils"),
        ("src/a.php", 14, "jsonEncode"),
        ("src/a.php", 15, "Logger.timezone"),
        ("src/a.php", 15, "VERSION"),
        ("src/a.php", 16, "Logger.pushHandler"),
    ]


def test_find_usages_php_same_namespace_and_fully_qualified():
    same = "<?php\nnamespace Monolog;\n$u = new Utils();\n"
    qualified = "<?php\n$h = new \\Monolog\\Handler\\StreamHandler('x');\n"

    report = find_usages(
        "composer",
        "monolog/monolog",
        MONOLOG,
        [("same.php", same), ("qualified.php", qualified)],
    )

    assert _hits(report) == [
        ("qualified.php", 2, "StreamHandler"),
        ("same.php", 3, "Utils"),
    ]


def test_find_usages_php_global_namespace():
    wanted = [
        ApiSymbol("class", "Parsedown", "\\", "removed"),
        ApiSymbol("function", "dump_value", "\\", "removed"),
        ApiSymbol("function", "e", "\\", "removed"),
    ]
    plain = "<?php\n$p = new Parsedown();\n"
    namespaced = (
        "<?php\nnamespace App;\ndump_value(1);\ne('x');\n$p = new Parsedown();\n"
    )

    report = find_usages(
        "composer",
        "erusev/parsedown",
        wanted,
        [("plain.php", plain), ("app.php", namespaced)],
    )

    # A global function is seen from any namespace; a global class isn't
    # (App\Parsedown), and a short function name is too common to look for.
    assert _hits(report) == [
        ("app.php", 3, "dump_value"),
        ("plain.php", 2, "Parsedown"),
    ]


def test_find_usages_php_import_line_when_never_used():
    text = "<?php\nuse Monolog\\Utils;\n"

    report = find_usages("composer", "monolog/monolog", MONOLOG, [("a.php", text)])

    assert _hits(report) == [("a.php", 2, "Utils")]


def test_find_usages_php_member_needs_its_owner():
    text = "<?php\n$log->pushHandler($h);\n$x = $y::DEBUG;\n"

    report = find_usages("composer", "monolog/monolog", MONOLOG, [("a.php", text)])

    assert report.total == 0
