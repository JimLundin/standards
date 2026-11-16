import pytest
from ordered import FrozenList

from checks.core.waivers import Issue, Waiver, kind, load, parse_waiver, waived

ENTRY = '[[exception]]\npath = "{path}"\nrule = "{rule}"\nreason = "{reason}"\n'


def test_waiver_covers_its_rule_and_glob() -> None:
    waiver = Waiver("src/**", "E501", "long")
    assert waiver.covers("src/a/b.py", "E501")
    assert not waiver.covers("src/a/b.py", "E502")
    assert not waiver.covers("tests/a.py", "E501")
    assert waived((waiver,), "src/x.py", "E501")
    assert not waived((waiver,), "src/x.py", "F401")
    assert not waived((), "src/x.py", "E501")


def test_parse_waiver_strips_fields() -> None:
    entry = {"path": " src/** ", "rule": " E501", "reason": "long "}
    assert parse_waiver(0, entry) == Waiver("src/**", "E501", "long")


def test_parse_waiver_rejects_unknown_keys_in_order() -> None:
    entry = {"path": "a", "rule": "b", "reason": "c", "zeta": 1, "alpha": 2}
    assert parse_waiver(2, entry) == Issue(
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
def test_parse_waiver_needs_all_fields(entry: object) -> None:
    assert parse_waiver(0, entry) == Issue(
        "exceptions.toml", "exception 1 needs a path, a rule and a reason"
    )


def test_load_without_a_file() -> None:
    waivers = load(None)
    assert waivers.entries == ()
    assert waivers.problems == ()


def test_load_reports_invalid_toml() -> None:
    waivers = load("[[exception]\n")
    assert waivers.entries == ()
    (problem,) = waivers.problems
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
    waivers = load(text)
    assert waivers.entries == (
        Waiver("a/**", "E501", "x"),
        Waiver("c", "F401", "y"),
    )
    assert isinstance(waivers.entries, FrozenList)
    assert waivers.problems == (
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
        ("rust", "std", "std"),
        ("rust", "api", "api"),
        ("rust", "shell", "shell"),
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
