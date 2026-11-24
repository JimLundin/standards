import pytest
from ordered import FrozenList, FrozenOrderedDict

from checks.core.structure import request, run
from checks.core.values import Inputs, Request
from tests.helpers import entry

WRAPS = "STR001 `f` adds no behaviour; inline it"
TARGET = "def g(x):\n    return x + 1\n\n"


def findings(
    texts: dict[str, str], exceptions: str | None = None
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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (f"{TARGET}def f(x):\n    return g(x)\n", "4:1"),
        ("def f(x):\n    return x\n", "1:1"),
        (f"{TARGET}async def f(x, y):\n    return g(y, x)\n", "4:1"),
        (f'{TARGET}def f(x):\n    """Doc."""\n    return g(x)\n', "4:1"),
        (f"{TARGET}def f(*x, **y):\n    return g(x, y)\n", "4:1"),
        (
            f"{TARGET}class A:\n    def f(self, x):\n        return g(x)\n",
            "5:5",
        ),
        ("class A:\n    pass\n\ndef f(x):\n    return A(x)\n", "4:1"),
        (f"{TARGET}def h():\n    def f(x):\n        return g(x)\n", "5:5"),
    ],
)
def test_a_trivial_wrapper_is_reported(source: str, expected: str) -> None:
    outcome = run(("m.py",), Inputs(FrozenOrderedDict({"m.py": source})))
    assert outcome.lines == (f"m.py:{expected}: {WRAPS}", "Found 1 issues")
    assert outcome.status == 1


def test_a_wrapper_of_a_function_imported_from_the_scanned_sources() -> None:
    assert findings({
        "pkg/__init__.py": "",
        "pkg/a.py": TARGET,
        "pkg/b.py": "from pkg.a import g\n\ndef f(x):\n    return g(x)\n",
        "pkg/c.py": "from . import a\n\ndef f(x):\n    return a.g(x)\n",
    }) == (f"pkg/b.py:3:1: {WRAPS}", f"pkg/c.py:3:1: {WRAPS}")


@pytest.mark.parametrize(
    "source",
    [
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
    ],
)
def test_a_wrapper_with_a_reason_to_exist_is_not_reported(source: str) -> None:
    assert findings({"m.py": source}) == ()


def test_an_exception_drops_the_findings_in_its_paths() -> None:
    sources = {"a.py": "def f(x):\n    return x\n", "b.py": TARGET}
    sources["c.py"] = sources["a.py"]
    assert findings(sources, entry("a.py", "STR001")) == (f"c.py:1:1: {WRAPS}",)


def test_an_exception_for_another_rule_drops_nothing() -> None:
    sources = {"a.py": "def f(x):\n    return x\n"}
    assert findings(sources, entry("a.py", "STR002")) == (f"a.py:1:1: {WRAPS}",)
