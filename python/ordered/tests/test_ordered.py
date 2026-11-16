from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet

from hypothesis import given
from hypothesis import strategies as st

from ordered import (
    FrozenList,
    FrozenOrderedDict,
    FrozenOrderedSet,
    OrderedCollection,
    OrderedMapping,
    OrderedSequence,
    OrderedSet,
)

words = st.lists(st.text(max_size=2), max_size=8)
pairs = st.lists(st.tuples(st.text(max_size=2), st.integers()), max_size=8)


def unique(values: Sequence[str]) -> FrozenList[str]:
    return FrozenList(dict.fromkeys(values))


@given(words)
def test_set_keeps_first_occurrence_order(values: Sequence[str]) -> None:
    items = FrozenOrderedSet(values)
    assert tuple(items) == unique(values)
    assert tuple(reversed(items)) == unique(values)[::-1]
    assert len(items) == len(unique(values))
    assert all(value in items for value in values)


@given(words, words)
def test_set_operations_keep_left_then_right_order(
    left: Sequence[str], right: Sequence[str]
) -> None:
    a, b = FrozenOrderedSet(left), FrozenOrderedSet(right)
    only_left = tuple(item for item in unique(left) if item not in b)
    only_right = tuple(item for item in unique(right) if item not in a)
    assert tuple(a & b) == tuple(item for item in unique(left) if item in b)
    assert tuple(a | b) == unique((*left, *right))
    assert tuple(a - b) == only_left
    assert tuple(a ^ b) == (*only_left, *only_right)
    assert isinstance(a | b, FrozenOrderedSet)


@given(words, words)
def test_set_equality_ignores_order(
    left: Sequence[str], right: Sequence[str]
) -> None:
    a, b = FrozenOrderedSet(left), FrozenOrderedSet(right)
    same = set(left) == set(right)
    assert (a == b) is same
    assert (a <= b) is (set(left) <= set(right))
    assert hash(FrozenOrderedSet(reversed(left))) == hash(a)
    assert hash(a) == hash(frozenset(left))


@given(pairs)
def test_dict_keeps_insertion_order_and_last_value(
    entries: Sequence[tuple[str, int]],
) -> None:
    table = FrozenOrderedDict(entries)
    expected = dict(entries)
    assert tuple(table.items()) == tuple(expected.items())
    assert tuple(table) == tuple(expected)
    assert tuple(table.values()) == tuple(expected.values())
    assert tuple(reversed(table)) == tuple(reversed(expected))
    assert tuple(reversed(table.items())) == tuple(reversed(expected.items()))
    assert tuple(reversed(table.values())) == tuple(reversed(expected.values()))
    assert table == expected
    assert len(table) == len(expected)


@given(pairs, pairs)
def test_dict_merge_matches_dict_merge(
    left: Sequence[tuple[str, int]], right: Sequence[tuple[str, int]]
) -> None:
    merged = FrozenOrderedDict(left) | dict(right)
    expected = dict(left) | dict(right)
    assert tuple(merged.items()) == tuple(expected.items())
    assert isinstance(merged, FrozenOrderedDict)


@given(pairs)
def test_dict_hash_ignores_order(entries: Sequence[tuple[str, int]]) -> None:
    table = FrozenOrderedDict(entries)
    backwards = FrozenOrderedDict(reversed(tuple(dict(entries).items())))
    assert table == backwards
    assert hash(table) == hash(backwards)


@given(pairs, words)
def test_views_are_ordered_sets(
    entries: Sequence[tuple[str, int]], other: Sequence[str]
) -> None:
    table = FrozenOrderedDict(entries)
    keys = table.keys()
    assert isinstance(keys, OrderedSet)
    assert isinstance(table.values(), OrderedCollection)
    assert isinstance(table.items(), OrderedSet)
    assert tuple(keys | FrozenOrderedSet(other)) == unique((*table, *other))
    assert tuple(reversed(keys)) == tuple(reversed(tuple(table)))


@given(words, words)
def test_list_operations_stay_frozen_lists(
    left: Sequence[str], right: Sequence[str]
) -> None:
    a, b = FrozenList(left), FrozenList(right)
    assert isinstance(a + b, FrozenList)
    assert a + b == (*left, *right)
    assert isinstance(a * 2, FrozenList)
    assert a * 2 == (*left, *left)
    assert isinstance(2 * a, FrozenList)
    assert isinstance(a[1:], FrozenList)
    assert a[1:] == tuple(left[1:])
    assert hash(a) == hash(tuple(left))
    if left:
        assert a[0] == left[0]


def test_capabilities() -> None:
    assert isinstance(FrozenList(()), OrderedSequence)
    assert isinstance(FrozenList(()), tuple)
    assert isinstance(FrozenOrderedSet(()), AbstractSet)
    assert isinstance(FrozenOrderedDict(()), OrderedMapping)
    assert isinstance(FrozenOrderedDict(()), Mapping)
    assert not isinstance(frozenset(), OrderedSet)
    assert not isinstance((), OrderedCollection)


def test_representations() -> None:
    assert repr(FrozenList(("a",))) == "FrozenList(('a',))"
    assert repr(FrozenOrderedSet(("b", "a"))) == "FrozenOrderedSet(['b', 'a'])"
    assert repr(FrozenOrderedDict({"b": 1})) == "FrozenOrderedDict({'b': 1})"
