lazy from collections.abc import Mapping

import pytest
from ordered import FrozenList, FrozenOrderedDict

from checks.core.python_source import request
from checks.core.structure import run
from checks.core.values import Inputs, Request
from tests.helpers import entry

WRAPS = "STR001 `f` adds no behaviour; inline it"
TARGET = "def g(x):\n    return x + 1\n\n"


def findings(
    texts: Mapping[str, str], exceptions: str | None = None
) -> FrozenList[str]:
    files = FrozenOrderedDict(texts)
    if exceptions is not None:
        files |= {"exceptions.toml": exceptions}
    return run(tuple(texts), Inputs(files)).lines[:-1]


def test_request_reads_the_exceptions_and_the_sources() -> None:
    assert request(("a.py", "b.py"), Inputs()) == Request(
        FrozenList(("exceptions.toml", "a.py", "b.py"))
    )


def test_clean_sources_pass() -> None:
    outcome = run(("m.py",), Inputs(FrozenOrderedDict({"m.py": TARGET})))
    assert outcome.lines == ("All checks passed",)
    assert outcome.status == 0


WRAPPERS = (
    (f"{TARGET}def f(x):\n    return g(x)\n", "4:1"),
    ("def f(x):\n    return x\n", "1:1"),
    (f"{TARGET}async def f(x, y):\n    return g(y, x)\n", "4:1"),
    (f'{TARGET}def f(x):\n    """Doc."""\n    return g(x)\n', "4:1"),
    (f"{TARGET}def f(*x, **y):\n    return g(x, y)\n", "4:1"),
    (f"{TARGET}class A:\n    def f(self, x):\n        return g(x)\n", "5:5"),
    ("class A:\n    pass\n\ndef f(x):\n    return A(x)\n", "4:1"),
    (f"{TARGET}def h():\n    def f(x):\n        return g(x)\n", "5:5"),
)


@pytest.mark.parametrize(("source", "expected"), WRAPPERS)
def test_a_trivial_wrapper_is_reported(source: str, expected: str) -> None:
    outcome = run(("m.py",), Inputs(FrozenOrderedDict({"m.py": source})))
    assert outcome.lines == (f"m.py:{expected}: {WRAPS}", "Found 1 issues")
    assert outcome.status == 1


PACKAGE = FrozenOrderedDict({
    "pkg/__init__.py": "",
    "pkg/a.py": TARGET,
    "pkg/b.py": "from pkg.a import g\n\ndef f(x):\n    return g(x)\n",
    "pkg/c.py": "from . import a\n\ndef f(x):\n    return a.g(x)\n",
})
NAMESPACE_PACKAGE = FrozenOrderedDict({
    "src/pkg/a.py": TARGET,
    "src/pkg/b.py": "from pkg.a import g\n\ndef f(x):\n    return g(x)\n",
    "src/pkg/c.py": "from .a import g\n\ndef f(x):\n    return g(x)\n",
})


def test_a_wrapper_of_a_function_imported_from_the_scanned_sources() -> None:
    assert findings(PACKAGE) == (
        f"pkg/b.py:3:1: {WRAPS}",
        f"pkg/c.py:3:1: {WRAPS}",
    )


def test_a_wrapper_of_a_function_in_a_namespace_package_under_src() -> None:
    assert findings(NAMESPACE_PACKAGE) == (
        f"src/pkg/b.py:3:1: {WRAPS}",
        f"src/pkg/c.py:3:1: {WRAPS}",
    )


KEPT_WRAPPERS = (
    "from ext import g\n\ndef f(x):\n    return g(x)\n",
    "def f(x):\n    return g(x)\n",
    f"{TARGET}@cache\ndef f(x):\n    return g(x)\n",
    f"{TARGET}class A:\n    def __call__(self, x):\n        return g(x)\n",
    f"{TARGET}class A(B):\n    def f(self, x):\n        return g(x)\n",
    f"{TARGET}class A(metaclass=M):\n    def f(self, x):\n        return g(x)\n",
    "def f(x):\n    return 1\n",
    f"{TARGET}def f(x):\n    return g(x=x)\n",
    f"{TARGET}def f(x):\n    return g(*x)\n",
    f"{TARGET}def f(x, y):\n    return g(x)\n",
    f"{TARGET}def f(x):\n    return g(x, x)\n",
    f"{TARGET}def f(x):\n    return g(x.y)\n",
    f"{TARGET}def f():\n    return g()\n",
    f"{TARGET}def f(x):\n    y = x\n    return g(y)\n",
    "def f(x):\n    return f(x)\n",
    "def f(x):\n    return\n",
    f"{TARGET}class A:\n    def f(self):\n        return self\n",
    f"{TARGET}class A:\n    def f(self, x):\n        return self.g(x)\n",
    f"{TARGET}if x:\n    def f(x):\n        return g(x)\n",
)


@pytest.mark.parametrize("source", KEPT_WRAPPERS)
def test_a_wrapper_with_a_reason_to_exist_is_not_reported(source: str) -> None:
    assert findings({"m.py": source}) == ()


WRAPPER = "def f(x):\n    return x\n"


def test_an_exception_drops_the_findings_in_its_paths() -> None:
    sources = {"a.py": WRAPPER, "b.py": TARGET, "c.py": WRAPPER}
    assert findings(sources, entry("a.py", "STR001")) == (f"c.py:1:1: {WRAPS}",)


def test_an_exception_for_another_rule_drops_nothing() -> None:
    sources = {"a.py": WRAPPER}
    assert findings(sources, entry("a.py", "STR002")) == (f"a.py:1:1: {WRAPS}",)


# Each score is worked by hand from scb-check 0.2.0's tree-sitter walk: a
# flow break scores 1 plus its nesting, with all its children one deeper.
ELIF_CHAIN = """\
def f(x):
    if x == 1:  # 1
        return 1
    elif x == 2:  # 1 + 1
        return 2
    elif x == 3:  # 1 + 1
        return 3
    else:  # 1 + 1
        for y in x:  # 1 + 2
            {}
"""
BOOLEAN_RUN = """\
def f(a, b, c, d):
    if a and b and c or d:  # 1, and three operators
        return 1
    while {}:  # 1, and its operators
        if c and not d:  # 1 + 1, and one operator
            continue  # 1
    return 0
"""
NESTED_FUNCTION = """\
def f(xs):
    def g(x):
        if x:  # 1
            return [y for y in x if y]
        return {}
    for x in xs:  # 1
        key = lambda y: y if y else x  # 1 + 1
        if key(x):  # 1 + 1
            try:
                g(x)
            except ValueError:  # 1 + 2
                break  # 1
    return xs
"""
CLAUSES = """\
def f(xs):
    for x in xs:  # 1
        try:
            pass
        except ValueError:  # 1 + 1
            continue  # 1
        else:  # 1 + 1
            pass
    else:  # 1 + 1
        while xs:  # 1 + 2
            pass
"""
ELSE_IF = """\
def f(x):
    for y in x:  # 1
        pass
    if x:  # 1
        pass
    else:  # 1 + 1
        if y:  # 1 + 2
            pass
        else:  # 1 + 3
            pass
"""


def complex_function(score: int) -> str:
    return f"STR002 `f` has cognitive complexity {score}, above 10; flatten it"


ABOVE_THE_LIMIT = (
    (ELIF_CHAIN.format("break  # 1"), 11),
    (BOOLEAN_RUN.format("a or b or c"), 11),
    (NESTED_FUNCTION.format("x if x else None  # 1"), 11),
    (CLAUSES, 11),
    (ELIF_CHAIN.format("pass").replace("x == 3:  #", "x and y:  # 1,"), 11),
    (ELSE_IF, 11),
)
AT_THE_LIMIT = (
    ELIF_CHAIN.format("pass"),
    BOOLEAN_RUN.format("a or b"),
    NESTED_FUNCTION.format("None"),
)


@pytest.mark.parametrize(("source", "score"), ABOVE_THE_LIMIT)
def test_a_function_above_the_cognitive_limit_is_reported(
    source: str, score: int
) -> None:
    assert findings({"m.py": source}) == (
        f"m.py:1:1: {complex_function(score)}",
    )


@pytest.mark.parametrize("source", AT_THE_LIMIT)
def test_a_function_at_the_cognitive_limit_is_not_reported(source: str) -> None:
    assert findings({"m.py": source}) == ()


def test_an_exception_drops_the_cognitive_findings_in_its_paths() -> None:
    source, score = ABOVE_THE_LIMIT[0]
    sources = {"a.py": source, "b.py": source}
    assert findings(sources, entry("a.py", "STR002")) == (
        f"b.py:1:1: {complex_function(score)}",
    )


def test_a_function_exception_drops_that_function_alone() -> None:
    source, score = ABOVE_THE_LIMIT[0]
    sources = {"a.py": f"{source}\n\n{source.replace('def f', 'def g')}"}
    assert findings(sources, entry("a.py", "STR002:f")) == (
        f"a.py:13:1: {complex_function(score).replace('`f`', '`g`')}",
    )


def test_a_method_exception_names_the_method_by_its_class() -> None:
    source, score = ABOVE_THE_LIMIT[0]
    body = "".join(f"    {line}\n" for line in source.splitlines())
    method = f"class C:\n{body}"
    sources = {"a.py": method, "b.py": method}
    assert findings(sources, entry("a.py", "STR002:C.f")) == (
        f"b.py:2:5: {complex_function(score)}",
    )


@pytest.mark.parametrize(
    "source",
    dict.fromkeys([
        WRAPPER,
        *(source for source, _ in WRAPPERS),
        *KEPT_WRAPPERS,
        *PACKAGE.values(),
        *NAMESPACE_PACKAGE.values(),
        *(source for source, _ in ABOVE_THE_LIMIT),
        *AT_THE_LIMIT,
    ]),
)
def test_every_fixture_is_valid_python(source: str) -> None:
    _ = compile(source, "m.py", "exec", dont_inherit=True)
