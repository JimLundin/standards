import pytest
from ordered import FrozenList, FrozenOrderedDict

from checks.core.immutability import run
from checks.core.python_source import request
from checks.core.values import Inputs, Request
from tests.helpers import entry

MUTABLE = (
    "in a parameter or field; use Sequence, Mapping, an Ordered type from "
    "ordered, or FrozenList, FrozenOrderedSet or FrozenOrderedDict"
)
UNORDERED = (
    "promises no order; use OrderedSet or OrderedCollection from ordered, or "
    "Container for membership only"
)
HASHED = (
    "iterates in hash order, which changes per process; use FrozenOrderedSet"
)


def findings(source: str, exceptions: str | None = None) -> FrozenList[str]:
    texts = FrozenOrderedDict({"m.py": source})
    if exceptions is not None:
        texts |= {"exceptions.toml": exceptions}
    outcome = run(("m.py",), Inputs(texts))
    return FrozenList(line.removeprefix("m.py:") for line in outcome.lines[:-1])


def test_request_reads_the_exceptions_and_the_sources() -> None:
    assert request(("a.py", "b.py"), Inputs()) == Request(
        FrozenList(("exceptions.toml", "a.py", "b.py"))
    )


def test_clean_file() -> None:
    outcome = run(
        ("m.py",), Inputs(FrozenOrderedDict({"m.py": "x = (1, 2)\n"}))
    )
    assert tuple(outcome.lines) == ("All checks passed",)
    assert outcome.status == 0


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("@dataclass\nclass A:\n    pass\n", "1:2: IMM001"),
        ("@dataclasses.dataclass()\nclass A:\n    pass\n", "1:2: IMM001"),
        ("@dataclass(frozen=False)\nclass A:\n    pass\n", "1:2: IMM001"),
        ("@dataclass(slots=True)\nclass A:\n    pass\n", "1:2: IMM001"),
        ('@dataclass(frozen="yes")\nclass A:\n    pass\n', "1:2: IMM001"),
    ],
)
def test_unfrozen_dataclasses(source: str, expected: str) -> None:
    assert findings(source) == (f"{expected} dataclass is not frozen=True",)


@pytest.mark.parametrize(
    "source",
    [
        "@dataclass(frozen=True)\nclass A:\n    pass\n",
        "@dataclass(slots=True, frozen=True)\nclass A:\n    pass\n",
        "@other\nclass A:\n    pass\n",
        "@obj.method\nclass A:\n    pass\n",
        "@registry[0]\nclass A:\n    pass\n",
    ],
)
def test_frozen_or_other_decorators(source: str) -> None:
    assert findings(source) == ()


@pytest.mark.parametrize(
    ("source", "name", "column"),
    [
        ("def f(x: list[int]) -> None: ...\n", "list", 10),
        ("def f(*, x: dict[str, int]) -> None: ...\n", "dict", 13),
        ("def f(x, /, y: bytearray) -> None: ...\n", "bytearray", 16),
        ("def f(*x: typing.List[int]) -> None: ...\n", "List", 11),
        ("def f(**x: Deque[int]) -> None: ...\n", "Deque", 12),
        ("async def f(x: MutableMapping) -> None: ...\n", "MutableMapping", 16),
        ("class A:\n    x: Counter[str]\n", "Counter", 8),
        ("def f(x: Sequence[defaultdict]) -> None: ...\n", "defaultdict", 19),
    ],
)
def test_mutable_annotations(source: str, name: str, column: int) -> None:
    line = source.count("\n", 0, source.index(name)) + 1
    assert (
        findings(source)[0]
        == f"{line}:{column}: IMM002 mutable type `{name}` {MUTABLE}"
    )


def test_mutable_annotation_reports_the_first_mutable_type_only() -> None:
    assert findings("def f(x: list[dict[str, int]]) -> None: ...\n") == (
        f"1:10: IMM002 mutable type `list` {MUTABLE}",
    )


def test_mutable_annotations_skip_returns_and_locals() -> None:
    source = "def f() -> list[int]:\n    x: list[int] = []\n    return x\n"
    assert findings(source) == ()


@pytest.mark.parametrize(
    "source",
    [
        "X = []\n",
        "X = {}\n",
        "X = [a for a in b]\n",
        "X = {a: b for a in c}\n",
        "X = list(y)\n",
        "X = dict()\n",
        "X: bytearray = bytearray()\n",
    ],
)
def test_mutable_globals(source: str) -> None:
    assert findings(source)[0].startswith(
        "1:1: IMM003 mutable module-level value"
    )


def test_mutable_global_message() -> None:
    assert findings("X = []\n") == (
        "1:1: IMM003 mutable module-level value; use a tuple, FrozenList or FrozenOrderedDict",
    )


@pytest.mark.parametrize(
    "source",
    [
        "X = (1,)\n",
        "X = f()\n",
        "X = obj.list()\n",
        "def f():\n    x = []\n",
        "X: int\n",
    ],
)
def test_immutable_globals(source: str) -> None:
    assert findings(source) == ()


@pytest.mark.parametrize(
    ("source", "built"),
    [
        ("x = {1, 2}\n", "a set literal"),
        ("x = {a for a in b}\n", "a set comprehension"),
        ("x = set(y)\n", "`set()`"),
        ("x = frozenset()\n", "`frozenset()`"),
    ],
)
def test_hash_ordered_sets(source: str, built: str) -> None:
    assert findings(source) == (f"1:5: IMM004 {built} {HASHED}",)


@pytest.mark.parametrize(
    "source",
    [
        "ok = x in {1, 2}\n",
        "ok = x not in {1, 2}\n",
        "ok = a < b in {1}\n",
        "x = obj.set()\n",
        "x = FrozenOrderedSet((1,))\n",
    ],
)
def test_membership_sets_and_other_calls(source: str) -> None:
    assert findings(source) == ()


def test_a_set_on_the_left_of_in_still_counts() -> None:
    assert findings("ok = {1} in x\n") == (
        f"1:6: IMM004 a set literal {HASHED}",
    )


def test_a_set_compared_by_equality_still_counts() -> None:
    assert findings("ok = x == {1}\n") == (
        f"1:11: IMM004 a set literal {HASHED}",
    )


@pytest.mark.parametrize(
    ("source", "name", "column"),
    [
        ("def f(x: set[int]) -> None: ...\n", "set", 10),
        ("def f(x) -> frozenset[int]: ...\n", "frozenset", 13),
        ("x: AbstractSet[int] = y\n", "AbstractSet", 4),
        ("type X = typing.FrozenSet[int]\n", "FrozenSet", 10),
        ("def f[T: Collection[int]](x: T) -> T: ...\n", "Collection", 10),
        ("def f(x: 'Set[int]') -> None: ...\n", "Set", 10),
    ],
)
def test_unordered_annotations(source: str, name: str, column: int) -> None:
    assert f"1:{column}: IMM005 `{name}` {UNORDERED}" in findings(source)


@pytest.mark.parametrize(
    ("source", "spelled", "wanted", "column"),
    [
        (
            "def f(x: tuple[int, ...]) -> None: ...\n",
            "tuple[T, ...]",
            "FrozenList[T]",
            10,
        ),
        (
            "def f(x) -> 'frozendict[str, int]': ...\n",
            "frozendict",
            "FrozenOrderedDict[K, V]",
            13,
        ),
        (
            "x: types.MappingProxyType[str, int] = y\n",
            "MappingProxyType",
            "FrozenOrderedDict[K, V]",
            4,
        ),
    ],
)
def test_unnamed_collections(
    source: str, spelled: str, wanted: str, column: int
) -> None:
    assert findings(source) == (
        f"1:{column}: IMM006 `{spelled}` has a name in ordered; use {wanted}",
    )


@pytest.mark.parametrize(
    "source",
    [
        "def f(x: tuple[int, str]) -> tuple[int]: ...\n",
        "def f(x: tuple[int, int, ...]) -> None: ...\n",
        "def f(x: tuple[...]) -> None: ...\n",
        "def f(x: Thing[int, ...]) -> None: ...\n",
        "def f(x: tuple[int, None]) -> None: ...\n",
        "class A:\n    __slots__: tuple[str, ...] = ()\n",
        "def f(x: 'not valid(') -> None: ...\n",
        "def f(x: Sequence[int], y: Mapping[str, int], z: Container[int]) -> None: ...\n",
        "def f[T](x: T) -> T: ...\n",
    ],
)
def test_allowed_annotations(source: str) -> None:
    assert findings(source) == ()


def test_findings_sort_by_position() -> None:
    source = "x = {1}\n@dataclass\nclass A:\n    y: list[int]\n"
    assert tuple(finding.split(" ")[1] for finding in findings(source)) == (
        "IMM004",
        "IMM001",
        "IMM002",
    )


def test_an_exception_covers_its_rule_in_matching_paths() -> None:
    source = "x = {1}\n@dataclass\nclass A:\n    pass\n"
    assert findings(source, entry("*.py", "IMM004")) == (
        "2:2: IMM001 dataclass is not frozen=True",
    )


@pytest.mark.parametrize(
    "exceptions",
    [
        entry("other.py", "IMM004"),
        entry("m.py", "IMM005"),
        "",
        "[[exception]\n",
        None,
    ],
)
def test_findings_outside_any_exception_are_reported(
    exceptions: str | None,
) -> None:
    source = "x = {1}\n@dataclass\nclass A:\n    pass\n"
    assert len(findings(source, exceptions)) == 2


def test_summary_counts_every_file() -> None:
    texts = FrozenOrderedDict({"a.py": "x = {1}\n", "b.py": "y = set()\n"})
    outcome = run(("a.py", "b.py"), Inputs(texts))
    assert tuple(outcome.lines) == (
        f"a.py:1:5: IMM004 a set literal {HASHED}",
        f"b.py:1:5: IMM004 `set()` {HASHED}",
        "Found 2 issues",
    )
    assert outcome.status == 1


def test_a_bad_string_annotation_does_not_hide_the_rest() -> None:
    assert findings(
        "def f(x: Mapping['bad(', frozenset[int]]) -> None: ...\n"
    ) == (f"1:26: IMM005 `frozenset` {UNORDERED}",)


def test_a_call_in_an_annotation_is_reported_once() -> None:
    assert findings(
        "def f(x: Annotated[int, MappingProxyType()]) -> None: ...\n"
    ) == (
        "1:25: IMM006 `MappingProxyType` has a name in ordered; use FrozenOrderedDict[K, V]",
    )


def test_syntax_errors_name_the_file() -> None:
    with pytest.raises(SyntaxError) as error:
        _ = run(("bad.py",), Inputs(FrozenOrderedDict({"bad.py": "def (:\n"})))
    assert error.value.filename == "bad.py"


def test_exception_globs_may_contain_colons() -> None:
    texts = FrozenOrderedDict({
        "c:x/m.py": "x = {1}\n",
        "exceptions.toml": entry("c:x/*.py", "IMM004"),
    })
    outcome = run(("c:x/m.py",), Inputs(texts))
    assert tuple(outcome.lines) == ("All checks passed",)
