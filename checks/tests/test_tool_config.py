import json

from ordered import FrozenList

from checks.core.tools import request, run
from checks.core.values import Inputs, Request
from tests.helpers import entry, inputs, lines


def test_each_subcommand_requests_exceptions_and_what_it_names() -> None:
    for command in ("ruff-config", "nextest-config"):
        assert request((command,), Inputs()) == Request(
            FrozenList(("exceptions.toml",))
        )
    for command in ("globs", "without"):
        assert request((command, "mutation", "a.py"), Inputs()) == Request(
            FrozenList(("exceptions.toml",))
        )
    for command in ("stryker-mutate", "biome-plugins"):
        assert request((command, "x.json"), Inputs()) == Request(
            FrozenList(("exceptions.toml", "x.json"))
        )
    assert request(("filter-mutmut",), Inputs()) == Request(
        FrozenList(("exceptions.toml",)), stdin=True
    )


def test_nextest_config_retries_each_flaky_test_once() -> None:
    texts = {
        "exceptions.toml": entry("provider_refresh_*", "flaky")
        + entry("src/a.rs", "api")
        + entry("tests::slow", "flaky")
    }
    assert lines(run(("nextest-config",), inputs(texts))) == (
        "[[profile.default.overrides]]",
        'filter = "test(#provider_refresh_*)"',
        "retries = 1",
        "[[profile.default.overrides]]",
        'filter = "test(#tests::slow)"',
        "retries = 1",
    )
    assert lines(run(("nextest-config",), inputs({}))) == ()


def test_ruff_config_groups_rules_by_path() -> None:
    texts = {
        "exceptions.toml": entry("a.py", "E501")
        + entry("b.py", "F401")
        + entry("a.py", "T201")
        + entry("a.py", "IMM001")
        + entry("a.py", "unused")
    }
    assert lines(run(("ruff-config",), inputs(texts))) == (
        'lint.extend-per-file-ignores = {"a.py" = ["E501", "T201"], "b.py" = ["F401"]}',
    )
    assert lines(run(("ruff-config",), inputs({}))) == ()


def test_without_and_globs() -> None:
    texts = {
        "exceptions.toml": entry("a/**", "unused") + entry("b.py", "mutation")
    }
    assert lines(
        run(("without", "unused", "a/x.py", "b.py"), inputs(texts))
    ) == ("b.py",)
    assert lines(run(("globs", "mutation"), inputs(texts))) == ("b.py",)
    assert lines(run(("globs", "api"), inputs(texts))) == ()


def test_biome_groups_by_shared_skips() -> None:
    texts = {
        "exceptions.toml": entry("a.ts", "lint/style/noVar")
        + entry("*.ts", "lint/style/useConst")
        + entry("*.ts", "lint/plugin/a")
        + entry("c.js", "mutation")
    }
    outcome = run(
        ("biome-groups", "a.ts", "b.ts", "c.js", "d.ts"), inputs(texts)
    )
    assert lines(outcome) == (
        "style/noVar style/useConst|a.ts",
        "style/useConst|b.ts|d.ts",
        "|c.js",
    )


def test_biome_plugins_resolve_against_the_config() -> None:
    config = json.dumps({"plugins": ["./p/a.grit", {"path": "../b.grit"}, {}]})
    outcome = run(
        ("biome-plugins", "conf/biome.json"),
        inputs({"conf/biome.json": config}, cwd="C:\\work"),
    )
    assert lines(outcome) == (
        "a|C:/work/conf/p/a.grit",
        "b|C:/work/b.grit",
        "|C:/work/conf",
    )
    absolute = run(
        ("biome-plugins", "/std/biome.json"),
        inputs({"/std/biome.json": config}, cwd="/home"),
    )
    assert lines(absolute)[0] == "a|/std/p/a.grit"


def test_filter_mutmut_drops_excepted_modules() -> None:
    texts = {
        "exceptions.toml": entry("src/app/shell.py", "mutation")
        + entry("app/cli/__init__.py", "mutation")
    }
    stdin = (
        "    app.shell.x__mutmut_1: survived\n"
        "app.cli.y__mutmut_2: survived\n"
        "app.core.z__mutmut_3: survived\n"
    )
    outcome = run(("filter-mutmut",), inputs(texts, stdin=stdin))
    assert lines(outcome) == ("app.core.z__mutmut_3: survived",)


def test_stryker_mutate_adds_excepted_globs() -> None:
    texts = {
        "exceptions.toml": entry("src/skip.ts", "mutation"),
        "stryker.json": json.dumps({"mutate": ["src/**", 3]}),
    }
    assert lines(run(("stryker-mutate", "stryker.json"), inputs(texts))) == (
        "src/**,!src/skip.ts",
    )


def test_stryker_mutate_is_empty_without_mutation_exceptions() -> None:
    texts = {
        "exceptions.toml": entry("src/a.ts", "lint/style/noVar"),
        "stryker.json": json.dumps({"mutate": ["src/**"]}),
    }
    assert lines(run(("stryker-mutate", "stryker.json"), inputs(texts))) == ()


def test_globs_lists_the_paths_an_exception_of_the_rule_covers() -> None:
    texts = {
        "exceptions.toml": entry("src/a.py", "PUR001:attrs")
        + entry("src/b.py", "PUR001:other")
    }
    assert lines(run(("globs", "PUR001:attrs.x"), inputs(texts))) == (
        "src/a.py",
    )
