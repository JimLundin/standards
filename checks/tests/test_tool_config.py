import json

from ordered import FrozenList

from checks.core.tools import request, run
from checks.core.values import Inputs, Request
from tests.helpers import entry, inputs, lines


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
