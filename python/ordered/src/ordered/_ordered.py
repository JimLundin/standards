from abc import ABCMeta
from collections.abc import (
    Collection,
    ItemsView,
    Iterable,
    Iterator,
    KeysView,
    Mapping,
    Reversible,
    Sequence,
    ValuesView,
)
from collections.abc import Set as AbstractSet
from types import MappingProxyType
from typing import Final, SupportsIndex, overload, override


class OrderedCollection[T](Reversible[T], Collection[T], metaclass=ABCMeta):
    __slots__: tuple[str, ...] = ()


class OrderedSequence[T](Sequence[T], OrderedCollection[T], metaclass=ABCMeta):
    __slots__: tuple[str, ...] = ()


class OrderedSet[T](AbstractSet[T], OrderedCollection[T], metaclass=ABCMeta):
    __slots__: tuple[str, ...] = ()

    @override
    def __and__(self, other: AbstractSet[object]) -> FrozenOrderedSet[T]:
        return FrozenOrderedSet(item for item in self if item in other)

    @override
    def __or__[S](self, other: AbstractSet[S]) -> FrozenOrderedSet[T | S]:
        return FrozenOrderedSet((*self, *other))

    @override
    def __sub__(self, other: AbstractSet[object]) -> FrozenOrderedSet[T]:
        return FrozenOrderedSet(item for item in self if item not in other)

    @override
    def __xor__[S](self, other: AbstractSet[S]) -> FrozenOrderedSet[T | S]:
        return FrozenOrderedSet((
            *(item for item in self if item not in other),
            *(item for item in other if item not in self),
        ))


class OrderedMapping[K, V](
    Mapping[K, V], OrderedCollection[K], metaclass=ABCMeta
):
    __slots__: tuple[str, ...] = ()

    @override
    def keys(self) -> OrderedKeysView[K]:
        return OrderedKeysView(self)

    @override
    def values(self) -> OrderedValuesView[V]:
        return OrderedValuesView(self)

    @override
    def items(self) -> OrderedItemsView[K, V]:
        return OrderedItemsView(self)


class OrderedKeysView[K](OrderedSet[K], KeysView[K]):
    @override
    def __reversed__(self) -> Iterator[K]:
        return reversed(tuple(self))


class OrderedValuesView[V](OrderedCollection[V], ValuesView[V]):
    @override
    def __reversed__(self) -> Iterator[V]:
        return reversed(tuple(self))


class OrderedItemsView[K, V](OrderedSet[tuple[K, V]], ItemsView[K, V]):
    @override
    def __reversed__(self) -> Iterator[tuple[K, V]]:
        return reversed(tuple(self))


class FrozenList[T](tuple[T, ...], OrderedSequence[T]):
    __slots__: tuple[str, ...] = ()

    @override
    def __add__[S](self, other: tuple[S, ...]) -> FrozenList[T | S]:
        return FrozenList((*self, *other))

    @override
    def __mul__(self, count: SupportsIndex) -> FrozenList[T]:
        return FrozenList(super().__mul__(count))

    @override
    def __rmul__(self, count: SupportsIndex) -> FrozenList[T]:
        return FrozenList(super().__rmul__(count))

    @overload
    def __getitem__(self, index: SupportsIndex) -> T: ...
    @overload
    def __getitem__(self, index: slice) -> FrozenList[T]: ...
    @override
    def __getitem__(self, index: SupportsIndex | slice) -> T | FrozenList[T]:
        if isinstance(index, slice):
            return FrozenList(super().__getitem__(index))
        return super().__getitem__(index)

    @override
    def __repr__(self) -> str:
        return f"FrozenList({super().__repr__()})"


class FrozenOrderedSet[T](OrderedSet[T]):
    __slots__: tuple[str, ...] = ("_items",)

    def __init__(self, items: Iterable[T] = ()) -> None:
        self._items: Final[MappingProxyType[T, None]] = MappingProxyType(
            dict.fromkeys(items)
        )

    @override
    def __contains__(self, item: object) -> bool:
        return item in self._items

    @override
    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    @override
    def __reversed__(self) -> Iterator[T]:
        return reversed(self._items)

    @override
    def __len__(self) -> int:
        return len(self._items)

    @override
    def __hash__(self) -> int:
        return self._hash()

    @override
    def __repr__(self) -> str:
        return f"FrozenOrderedSet({list(self._items)!r})"


class FrozenOrderedDict[K, V](OrderedMapping[K, V]):
    __slots__: tuple[str, ...] = ("_items",)

    def __init__(
        self, items: Mapping[K, V] | Iterable[tuple[K, V]] = ()
    ) -> None:
        self._items: Final[MappingProxyType[K, V]] = MappingProxyType(
            dict(items)
        )

    @override
    def __getitem__(self, key: K) -> V:
        return self._items[key]

    @override
    def __iter__(self) -> Iterator[K]:
        return iter(self._items)

    @override
    def __reversed__(self) -> Iterator[K]:
        return reversed(self._items)

    @override
    def __len__(self) -> int:
        return len(self._items)

    @override
    def __hash__(self) -> int:
        return hash(FrozenOrderedSet(self._items.items()))

    def __or__[L, W](
        self, other: Mapping[L, W]
    ) -> FrozenOrderedDict[K | L, V | W]:
        return FrozenOrderedDict({**self._items, **other})

    @override
    def __repr__(self) -> str:
        return f"FrozenOrderedDict({dict(self._items)!r})"
