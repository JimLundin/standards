import pytest
from ordered import FrozenList

from checks.core.exceptions import (
    ExceptionEntry,
    Exceptions,
    Issue,
    kind,
    load,
    parse_entry,
)
from tests.helpers import entry


def exceptions_for(excepted: str) -> Exceptions:
    return load(entry("src/**", excepted))


@pytest.mark.parametrize(
    ("excepted", "rule", "path"),
    [
        ("E501", "E501", "src/a/b.py"),
        ("PUR001", "PUR001:attrs.x", "src/a.py"),
        ("PUR003", "PUR003", "src/a.py"),
        ("PUR001:attrs", "PUR001:attrs", "src/a.py"),
        ("PUR001:attrs", "PUR001:attrs.x", "src/a.py"),
        ("api", "api", "src/lib.rs"),
        ("shell", "shell", "src/main.rs"),
    ],
)
def test_an_exception_covers_its_rule_in_matching_paths(
    excepted: str, rule: str, path: str
) -> None:
    assert exceptions_for(excepted).covers(rule, path)


@pytest.mark.parametrize(
    ("excepted", "rule", "path"),
    [
        ("E501", "E502", "src/a/b.py"),
        ("E501", "E501", "tests/a.py"),
        ("drift:tool", "drift:tool.ruff", "src/a.py"),
        ("PUR001", "PUR002:attrs", "src/a.py"),
        ("PUR001:attrs", "PUR001:attrsx", "src/a.py"),
        ("PUR001:attrs", "PUR001", "src/a.py"),
        ("PUR001:attrs", "PUR001:attrs", "tests/a.py"),
        ("shell", "api", "src/lib.rs"),
        ("api", "shell", "src/lib.rs"),
    ],
)
def test_an_exception_leaves_other_rules_and_paths(
    excepted: str, rule: str, path: str
) -> None:
    assert not exceptions_for(excepted).covers(rule, path)


def test_parse_entry_strips_fields() -> None:
    fields = {"path": " src/** ", "rule": " E501", "reason": "long "}
    assert parse_entry(0, fields) == ExceptionEntry("src/**", "E501", "long")


def test_parse_entry_rejects_unknown_keys_in_order() -> None:
    fields = {"path": "a", "rule": "b", "reason": "c", "zeta": 1, "alpha": 2}
    assert parse_entry(2, fields) == Issue(
        "exceptions.toml", "exception 3 has unknown keys: alpha, zeta"
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"path": "a", "rule": "b"},
        {"path": "a", "rule": "b", "reason": " "},
        {"path": "a", "rule": 1, "reason": "c"},
        "not a table",
    ],
)
def test_parse_entry_needs_all_fields(fields: object) -> None:
    assert parse_entry(0, fields) == Issue(
        "exceptions.toml", "exception 1 needs a path, a rule and a reason"
    )


def test_load_without_a_file() -> None:
    exceptions = load(None)
    assert exceptions.entries == ()
    assert exceptions.problems == ()


def test_load_reports_invalid_toml() -> None:
    exceptions = load("[[exception]\n")
    assert exceptions.entries == ()
    (problem,) = exceptions.problems
    assert problem.path == "exceptions.toml"
    assert problem.message.startswith("invalid TOML: ")
    assert len(problem.message) > len("invalid TOML: ")


def test_load_keeps_entries_and_reports_problems_in_order() -> None:
    text = (
        entry("a/**", "E501", "x")
        + "[[exception]]\npath = 'b'\n"
        + entry("c", "F401", "y")
        + "[other]\n[more]\n"
    )
    exceptions = load(text)
    assert exceptions.entries == (
        ExceptionEntry("a/**", "E501", "x"),
        ExceptionEntry("c", "F401", "y"),
    )
    assert isinstance(exceptions.entries, FrozenList)
    assert exceptions.problems == (
        Issue(
            "exceptions.toml", "exception 2 needs a path, a rule and a reason"
        ),
        Issue("exceptions.toml", "unknown table `other`"),
        Issue("exceptions.toml", "unknown table `more`"),
    )


@pytest.mark.parametrize(
    ("language", "rule", "expected"),
    [
        ("python", "mutation", "mutation"),
        ("rust", "mutation", "mutation"),
        ("typescript", "mutation", "mutation"),
        ("rust", "std", "attribute"),
        ("rust", "api", "api"),
        ("rust", "shell", "shell"),
        ("rust", "flaky", "flaky"),
        ("python", "flaky", "ruff"),
        ("typescript", "flaky", ""),
        ("python", "std", "ruff"),
        ("typescript", "api", ""),
        ("python", "drift:tool.ruff", "drift"),
        ("rust", "drift:x", "drift"),
        ("python", "IMM002", "immutability"),
        ("python", "IMM02", "ruff"),
        ("python", "PUR001", "purity"),
        ("python", "PUR001:attrs.x", "purity"),
        ("python", "PUR001:", "ruff"),
        ("python", "unused", "unused"),
        ("python", "E501", "ruff"),
        ("rust", "clippy::shadow_reuse", "attribute"),
        ("rust", "dead_code", "attribute"),
        ("rust", "Dead-Code", ""),
        ("typescript", "lint/typescript/no-floating-promises", "oxlint"),
        ("typescript", "lint/eslint/no-bitwise", "oxlint"),
        ("typescript", "lint/standards/no-module-state", "oxlint"),
        ("typescript", "lint/no-bitwise", ""),
        ("typescript", "typescript/no-floating-promises", ""),
        ("typescript", "purity:lodash", "purity"),
        ("typescript", "purity:@effect/platform-node/NodeRuntime", "purity"),
        ("typescript", "purity:", ""),
        ("python", "purity:lodash", "ruff"),
        ("go", "lint/eslint/no-bitwise", ""),
    ],
)
def test_kind(language: str, rule: str, expected: str) -> None:
    assert kind(language, rule) == expected
