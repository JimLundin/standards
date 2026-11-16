lazy from collections.abc import Sequence

import pytest
from hypothesis import given
from hypothesis import strategies as st
from ordered import FrozenList, FrozenOrderedDict

from checks.core.values import (
    EMPTY,
    Inputs,
    Outcome,
    Request,
    absolute,
    entries,
    lookup,
    matches,
    normalized,
    operands,
    options,
    parse_json,
    parse_toml,
    posix,
    strings,
    summarized,
    table,
)

segments = st.lists(st.sampled_from(("a", "b", ".", "..", "")), max_size=6)


def test_defaults_are_empty() -> None:
    assert Inputs() == Inputs(FrozenOrderedDict(), "", "")
    assert Request() == Request(FrozenList(), stdin=False)
    assert Outcome() == Outcome(FrozenList(), 0, FrozenOrderedDict())


def test_table_accepts_only_mappings() -> None:
    assert table({"a": 1}) == {"a": 1}
    assert table([("a", 1)]) is EMPTY
    assert table(None) is EMPTY


def test_entries_and_strings_read_lists() -> None:
    assert entries([1, "a"]) == (1, "a")
    assert isinstance(entries([1]), FrozenList)
    assert entries((1,)) == ()
    assert strings(["a", 1, "b"]) == ("a", "b")
    assert strings("a") == ()


def test_lookup_follows_dotted_keys() -> None:
    data = {"tool": {"ruff": {"lint": 1}}}
    assert lookup(data, "tool.ruff.lint") == 1
    assert lookup(data, "tool.missing.lint") is None
    assert lookup(data, "tool") == {"ruff": {"lint": 1}}


def test_parse_toml() -> None:
    assert parse_toml(None) is EMPTY
    assert parse_toml("a = 1\n") == {"a": 1}


def test_parse_json() -> None:
    assert parse_json(None) is EMPTY
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json("[1]") is EMPTY
    assert parse_json("{") is EMPTY


def test_matches_uses_full_path_globs() -> None:
    assert matches("src/a/b.py", "src/**")
    assert matches("src/a.py", "src/*.py")
    assert not matches("src/a/b.py", "src/*.py")
    assert not matches("x/src/a.py", "src/*.py")


def test_posix_and_absolute() -> None:
    assert posix("a\\b\\c") == "a/b/c"
    assert absolute("biome.json", "C:\\work") == "C:/work/biome.json"
    assert absolute("C:\\x\\biome.json", "/home") == "C:/x/biome.json"
    assert absolute("/etc/biome.json", "/home") == "/etc/biome.json"
    assert absolute("d:/x", "/home") == "d:/x"
    assert absolute("ab:/x", "/home") == "/home/ab:/x"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a/./b", "a/b"),
        ("a/b/../c", "a/c"),
        ("/a/../../b", "/b"),
        ("../a", "../a"),
        ("a/../../b", "../b"),
        ("a//b", "a/b"),
        ("C:\\x\\..\\y", "C:/y"),
        ("./a", "a"),
        ("", ""),
    ],
)
def test_normalized(path: str, expected: str) -> None:
    assert normalized(path) == expected


@given(segments)
def test_normalized_is_idempotent_and_drops_dots(parts: Sequence[str]) -> None:
    once = normalized("/".join(parts))
    assert normalized(once) == once
    assert "." not in once.split("/")


def test_summarized() -> None:
    assert summarized(()) == Outcome(FrozenList(("All checks passed",)), 0)
    assert summarized(("a", "b")) == Outcome(
        FrozenList(("a", "b", "Found 2 issues")), 1
    )


def test_options_and_operands_split_arguments() -> None:
    arguments = ("--skip=a", "x", "--skip=b", "--other", "y")
    assert options(arguments, "--skip=") == ("a", "b")
    assert operands(arguments) == ("x", "y")
    assert isinstance(options(arguments, "--skip="), FrozenList)
    assert isinstance(operands(arguments), FrozenList)


def test_normalized_keeps_leading_parents() -> None:
    assert normalized("../../a") == "../../a"
    assert normalized("a/../../../b") == "../../b"
