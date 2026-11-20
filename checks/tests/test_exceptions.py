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

ENTRY = '[[exception]]\npath = "{path}"\nrule = "{rule}"\nreason = "{reason}"\n'


def exceptions_for(excepted: str) -> Exceptions:
    return load(ENTRY.format(path="src/**", rule=excepted, reason="r"))


@pytest.mark.parametrize(
    ("excepted", "rule", "path"), [("E501", "E501", "src/a/b.py")]
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
    ],
)
def test_an_exception_leaves_other_rules_and_paths(
    excepted: str, rule: str, path: str
) -> None:
    assert not exceptions_for(excepted).covers(rule, path)


def test_parse_entry_strips_fields() -> None:
    entry = {"path": " src/** ", "rule": " E501", "reason": "long "}
    assert parse_entry(0, entry) == ExceptionEntry("src/**", "E501", "long")


def test_parse_entry_rejects_unknown_keys_in_order() -> None:
    entry = {"path": "a", "rule": "b", "reason": "c", "zeta": 1, "alpha": 2}
    assert parse_entry(2, entry) == Issue(
        "exceptions.toml", "exception 3 has unknown keys: alpha, zeta"
    )


@pytest.mark.parametrize(
    "entry",
    [
        {"path": "a", "rule": "b"},
        {"path": "a", "rule": "b", "reason": " "},
        {"path": "a", "rule": 1, "reason": "c"},
        "not a table",
    ],
)
def test_parse_entry_needs_all_fields(entry: object) -> None:
    assert parse_entry(0, entry) == Issue(
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
        ENTRY.format(path="a/**", rule="E501", reason="x")
        + "[[exception]]\npath = 'b'\n"
        + ENTRY.format(path="c", rule="F401", reason="y")
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
        ("typescript", "lint/style/noVar", "biome"),
        ("typescript", "style/noVar", ""),
        ("go", "lint/x", ""),
    ],
)
def test_kind(language: str, rule: str, expected: str) -> None:
    assert kind(language, rule) == expected
