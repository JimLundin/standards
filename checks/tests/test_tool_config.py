import json
import tomllib
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList

from checks.core.tools import request, run
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    lookup,
    matches,
    strings,
    table,
)
from tests.helpers import assert_lines_name_the_fix, entry, inputs, lines


def test_each_subcommand_requests_exceptions_and_what_it_names() -> None:
    for command in ("ruff-config", "nextest-config", "oxlint-config"):
        assert request((command,), Inputs()) == Request(
            FrozenList(("exceptions.toml",))
        )
    assert request(("globs", "mutation"), Inputs()) == Request(
        FrozenList(("exceptions.toml",))
    )
    for command in ("stryker-mutate", "stryker-config"):
        assert request((command, "x.json", "v.ts"), Inputs()) == Request(
            FrozenList(("exceptions.toml", "x.json"))
        )
    for command in ("filter-mutmut", "filter-vulture"):
        assert request((command,), Inputs()) == Request(
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


def ruff_ignores(texts: Mapping[str, str]) -> Mapping[str, FrozenList[str]]:
    (line,) = lines(run(("ruff-config",), inputs(texts)))
    config: Mapping[str, object] = tomllib.loads(line)
    ignores = table(lookup(config, "lint.extend-per-file-ignores"))
    return {glob: strings(rules) for glob, rules in ignores.items()}


def test_ruff_config_groups_rules_by_path() -> None:
    texts = {
        "exceptions.toml": entry("a.py", "E501")
        + entry("b.py", "F401")
        + entry("a.py", "T201")
        + entry("a.py", "IMM001")
        + entry("a.py", "unused")
    }
    ignores = ruff_ignores(texts)
    assert ignores["a.py"] == ("E501", "T201")
    assert ignores["b.py"] == ("F401",)


def ignored_in(path: str) -> FrozenList[str]:
    return FrozenList(
        rule
        for glob, rules in ruff_ignores({}).items()
        if matches(path, glob)
        for rule in rules
    )


def test_ruff_config_gives_test_files_the_test_ignores() -> None:
    for path in ("test/helpers.py", "pkg/__tests__/a.py", "conftest.py"):
        assert "assert" in ignored_in(path), path
    assert ignored_in("src/testing.py") == ()


def test_globs() -> None:
    texts = {
        "exceptions.toml": entry("a/**", "unused") + entry("b.py", "mutation")
    }
    assert lines(run(("globs", "mutation"), inputs(texts))) == ("b.py",)
    assert lines(run(("globs", "api"), inputs(texts))) == ()


OXLINT_CONFIG = """import config from "file:///std/oxlint.config.ts";

export default {
	extends: [config],
	overrides: [
		{ files: ["/work/src/b.ts"], rules: { "eslint/no-bitwise": "off" } },
		{ files: ["/work/**/*.test.ts"], rules: { "typescript/no-floating-promises": "off" } },
	],
};
"""


def test_oxlint_config_extends_the_config_with_an_override_per_exception() -> (
    None
):
    texts = {
        "exceptions.toml": entry("src/b.ts", "lint/eslint/no-bitwise")
        + entry("src/c.ts", "mutation")
        + entry("**/*.test.ts", "lint/typescript/no-floating-promises")
    }
    outcome = run(
        ("oxlint-config", "/std/oxlint.config.ts"), inputs(texts, cwd="/work")
    )
    written = "node_modules/.cache/standards/oxlint.config.mjs"
    assert lines(outcome) == (written,)
    assert outcome.writes == {written: OXLINT_CONFIG}


def test_oxlint_config_turns_off_a_scoped_plugins_rule() -> None:
    texts = {
        "exceptions.toml": entry("a.ts", "lint/@nkzw/no-instanceof")
        + entry("b.ts", "lint/@scope/plugin/a-rule")
    }
    outcome = run(
        ("oxlint-config", "/std/oxlint.config.ts"), inputs(texts, cwd="/work")
    )
    (config,) = outcome.writes.values()
    assert (
        '{ files: ["/work/a.ts"], rules: { "@nkzw/no-instanceof": "off" } },'
        in config
    )
    assert (
        '{ files: ["/work/b.ts"], rules: { "@scope/plugin/a-rule": "off" } },'
        in config
    )


def test_oxlint_config_anchors_globs_at_a_windows_project_root() -> None:
    texts = {"exceptions.toml": entry("*.ts", "lint/eslint/no-var")}
    outcome = run(
        ("oxlint-config", "conf/oxlint.config.ts"),
        inputs(texts, cwd="C:\\work"),
    )
    (config,) = outcome.writes.values()
    assert (
        'import config from "file:///C:/work/conf/oxlint.config.ts";' in config
    )
    assert (
        '{ files: ["C:/work/*.ts"], rules: { "eslint/no-var": "off" } },'
        in config
    )


def test_oxlint_config_imports_the_config_by_an_escaped_file_url() -> None:
    outcome = run(
        ("oxlint-config", "my std/oxlint.config.ts"), inputs({}, cwd="/work")
    )
    (config,) = outcome.writes.values()
    assert (
        'import config from "file:///work/my%20std/oxlint.config.ts";' in config
    )


def test_oxlint_config_untyped_turns_type_aware_rules_off() -> None:
    outcome = run(
        ("oxlint-config", "--untyped", "/std/oxlint.config.ts"),
        inputs({}, cwd="/work"),
    )
    (config,) = outcome.writes.values()
    assert config == (
        'import config from "file:///std/oxlint.config.ts";\n\n'
        "export default {\n"
        "\textends: [config],\n"
        "\toptions: { ...config.options, typeAware: false },\n"
        "\toverrides: [\n\t],\n"
        "};\n"
    )


def test_oxlint_config_turns_a_standards_plugin_rule_off() -> None:
    texts = {
        "exceptions.toml": entry("src/a.ts", "lint/standards/no-module-state")
    }
    outcome = run(
        ("oxlint-config", "/std/oxlint.config.ts"), inputs(texts, cwd="/work")
    )
    (config,) = outcome.writes.values()
    override = '{ files: ["/work/src/a.ts"], rules: { "standards/no-module-state": "off" } },'
    assert override in config


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


def test_filter_vulture_drops_findings_in_files_excepted_from_unused() -> None:
    texts = {
        "exceptions.toml": entry("app/shell/**", "unused")
        + entry("app/core.py", "mutation")
    }
    stdin = (
        "app/shell/cli.py:3: unused function 'main' (60% confidence)\n"
        "app\\shell\\io.py:9: unused variable 'x' (60% confidence)\n"
        "app/core.py:5: unused function 'f' (60% confidence)\n"
    )
    outcome = run(("filter-vulture",), inputs(texts, stdin=stdin))
    assert lines(outcome) == (
        "app/core.py:5: unused function 'f' (60% confidence)",
    )


ORDERED = "src/ordered/_ordered.py"
ORDERED_SOURCE = """\
class OrderedMapping:
    def keys(self):
        return ()

    @property
    def values(self):
        return ()


def _never_called():
    return 1
"""
KEYS = f"{ORDERED}:2: unused method 'keys' (60% confidence)"
VALUES = f"{ORDERED}:5: unused property 'values' (60% confidence)"
NEVER_CALLED = f"{ORDERED}:10: unused function '_never_called' (60% confidence)"


def named_entry(path: str, names: Sequence[str]) -> str:
    return entry(path, "unused") + f"names = {json.dumps(list(names))}\n"


def filtered(
    names: Sequence[str], findings: Sequence[str], read: Sequence[str]
) -> Outcome:
    texts = {
        "exceptions.toml": named_entry(ORDERED, names),
        ORDERED: ORDERED_SOURCE,
    }
    stdin = "".join(f"{finding}\n" for finding in findings)
    return run(("filter-vulture", *read), inputs(texts, stdin=stdin))


def test_filter_vulture_requests_the_files_a_named_exception_covers() -> None:
    texts = {"exceptions.toml": named_entry("src/**", ("A.f",))}
    arguments = ("filter-vulture", "src/a.py", "tests/b.py")
    assert request(arguments, inputs(texts)) == Request(
        FrozenList(("exceptions.toml", "src/a.py")), stdin=True
    )


def test_an_exception_naming_an_item_drops_only_that_items_findings() -> None:
    findings = (KEYS, VALUES, NEVER_CALLED)
    outcome = filtered(("OrderedMapping.keys",), findings, (ORDERED,))
    assert lines(outcome) == (VALUES, NEVER_CALLED)


def test_a_name_qualifies_a_decorated_item_by_its_class() -> None:
    names = ("OrderedMapping.keys", "OrderedMapping.values")
    outcome = filtered(names, (KEYS, VALUES, NEVER_CALLED), (ORDERED,))
    assert lines(outcome) == (NEVER_CALLED,)


def test_an_excepted_name_matching_no_finding_is_reported() -> None:
    names = ("OrderedMapping.keys", "OrderedMapping.items")
    outcome = filtered(names, (KEYS,), (ORDERED,))
    assert lines(outcome) == (
        (
            f"exceptions.toml ({ORDERED}): unused name `OrderedMapping.items`"
            " matches no finding; fix: remove it from `names`"
        ),
    )
    assert_lines_name_the_fix(
        line.partition(": ")[2] for line in lines(outcome)
    )


def test_names_in_a_file_vulture_did_not_read_are_not_reported() -> None:
    outcome = filtered(("OrderedMapping.items",), (), ("tests/test_a.py",))
    assert lines(outcome) == ()


PROBE = "src/ordered/test_probe.py"
PROBE_SOURCE = """\
from ordered._ordered import OrderedMapping


def test_keys():
    assert OrderedMapping().keys() == ()
"""


def unit_over(read: str, findings: Sequence[str]) -> Outcome:
    texts = {
        "exceptions.toml": named_entry(
            "src/ordered/*.py", ("OrderedMapping.keys",)
        ),
        ORDERED: ORDERED_SOURCE,
        PROBE: PROBE_SOURCE,
    }
    stdin = "".join(f"{finding}\n" for finding in findings)
    return run(("filter-vulture", read), inputs(texts, stdin=stdin))


def test_a_name_is_stale_only_on_the_side_that_holds_its_item() -> None:
    assert lines(unit_over(ORDERED, (KEYS,))) == ()
    assert lines(unit_over(PROBE, ())) == ()


def test_a_name_of_an_item_in_a_test_file_is_stale_on_the_tests_side() -> None:
    texts = {
        "exceptions.toml": named_entry("src/ordered/*.py", ("test_keys",)),
        PROBE: PROBE_SOURCE,
    }
    outcome = run(("filter-vulture", PROBE), inputs(texts))
    assert lines(outcome) == (
        (
            "exceptions.toml (src/ordered/*.py): unused name `test_keys`"
            " matches no finding; fix: remove it from `names`"
        ),
    )


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


def test_stryker_config_points_a_copy_at_the_vitest_config() -> None:
    texts = {
        "stryker.json": json.dumps({
            "mutate": ["src/**"],
            "vitest": {"related": False},
        })
    }
    outcome = run(
        ("stryker-config", "stryker.json", "cache/vitest.config.ts"),
        inputs(texts),
    )
    written = "node_modules/.cache/standards/stryker.config.json"
    assert lines(outcome) == (written,)
    assert json.loads(outcome.writes[written]) == {
        "mutate": ["src/**"],
        "vitest": {"related": False, "configFile": "cache/vitest.config.ts"},
    }


def test_stryker_config_adds_the_vitest_table_a_config_lacks() -> None:
    texts = {"stryker.json": json.dumps({"mutate": ["src/**"]})}
    outcome = run(("stryker-config", "stryker.json", "v.ts"), inputs(texts))
    (config,) = outcome.writes.values()
    assert json.loads(config) == {
        "mutate": ["src/**"],
        "vitest": {"configFile": "v.ts"},
    }


def test_globs_lists_the_paths_an_exception_of_the_rule_covers() -> None:
    texts = {
        "exceptions.toml": entry("src/a.py", "PUR001:attrs")
        + entry("src/b.py", "PUR001:other")
    }
    assert lines(run(("globs", "PUR001:attrs.x"), inputs(texts))) == (
        "src/a.py",
    )
