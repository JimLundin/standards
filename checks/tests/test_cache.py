lazy from collections.abc import Sequence

from hypothesis import given
from hypothesis import strategies as st

from checks.core.cache import above, below, key, passes, request, run, seen
from checks.core.values import Inputs, Request

FIELDS = ("rust", "abc123", "standards-tree", "project-tree")


def test_a_key_is_a_sha256_of_its_fields() -> None:
    assert key(FIELDS) == key(FIELDS)
    assert len(key(FIELDS)) == 64
    assert all(character in "0123456789abcdef" for character in key(FIELDS))


@given(st.lists(st.text(), min_size=1), st.integers(0, 10), st.text())
def test_any_changed_field_changes_the_key(
    fields: Sequence[str], index: int, other: str
) -> None:
    position = index % len(fields)
    changed = [*fields[:position], other, *fields[position + 1 :]]
    assert (key(fields) == key(changed)) == (fields == changed)


def test_field_boundaries_are_part_of_the_key() -> None:
    assert key(("ab", "c")) != key(("a", "bc"))
    assert key(("a",)) != key(("a", ""))


def test_tiers_above_and_below() -> None:
    assert above("commit") == ("step", "release")
    assert above("release") == ()
    assert below("release") == ("step", "commit")
    assert below("commit") == ()


def test_a_pass_is_accepted_from_its_tier_and_higher_ones() -> None:
    step = passes("step", *FIELDS)
    release = passes("release", *FIELDS)
    commit = passes("commit", *FIELDS)
    assert len(step) == 2
    assert step[1] == release[0]
    assert commit[1:] == step
    assert passes("step", "rust", "other-base", *FIELDS[2:])[0] != step[0]
    assert passes("step", "python", *FIELDS[1:])[0] != step[0]


def test_a_whole_run_is_seen_at_its_tier_and_lower_ones() -> None:
    release = seen("release", "rust", "standards", "repo")
    assert len(release) == 3
    assert seen("step", "rust", "standards", "repo") == release[1:]
    assert seen("step", "rust", "newer", "repo")[0] != release[1]
    assert seen("step", "rust", "standards", "repo")[0] not in passes(
        "step", *FIELDS
    )


def test_the_tool_prints_pass_then_seen_keys() -> None:
    arguments = ("step", "rust", "base", "standards", "tree", "repo")
    assert request(arguments, Inputs()) == Request()
    lines = run(arguments, Inputs()).lines
    assert lines == (
        *(
            f"pass {item}"
            for item in passes("step", "rust", "base", "standards", "tree")
        ),
        *(f"seen {item}" for item in seen("step", "rust", "standards", "repo")),
    )
