import json
lazy from collections.abc import Sequence

import pytest
from ordered import FrozenList, FrozenOrderedDict

from checks.core.purity import core_modules, request, run, source
from checks.core.values import Inputs, Request

IMPORTS = "it may import itself, pure standard modules and a PUR001:<module> exception"
ONLY_DATA = "the core's public API takes only data"
PYPROJECT = """
[[tool.importlinter.contracts]]
type = "layers"
containers = ["app"]
layers = ["(__main__)", "shell", "core"]
"""


def findings(
    code: str, path: str = "src/app/core/m.py", *skips: str
) -> FrozenList[str]:
    texts = FrozenOrderedDict({"pyproject.toml": PYPROJECT, path: code})
    outcome = run((*skips, path), Inputs(texts))
    return FrozenList(
        line.removeprefix(f"{path}:") for line in outcome.lines[:-1]
    )


def test_request_reads_pyproject_and_operands() -> None:
    assert request(("--skips=[]", "a.py"), Inputs()) == Request(
        FrozenList(("pyproject.toml", "a.py"))
    )


@pytest.mark.parametrize(
    ("pyproject", "expected"),
    [
        (PYPROJECT, ("app.core",)),
        (
            '[[tool.importlinter.contracts]]\ntype = "layers"\ncontainers = ["a", "b"]\nlayers = ["x", "(c | d : e)"]\n',
            ("a.c", "a.d", "a.e", "b.c", "b.d", "b.e"),
        ),
        (
            '[[tool.importlinter.contracts]]\ntype = "layers"\ncontainers = ["a"]\nlayers = []\n',
            (),
        ),
        (
            '[[tool.importlinter.contracts]]\ntype = "forbidden"\ncontainers = ["a"]\nlayers = ["c"]\n',
            (),
        ),
        (None, ()),
    ],
)
def test_core_modules(pyproject: str | None, expected: Sequence[str]) -> None:
    assert core_modules(pyproject) == expected


@pytest.mark.parametrize(
    ("path", "module", "package"),
    [
        ("src/app/core/m.py", "app.core.m", False),
        ("app/core/__init__.py", "app.core", True),
        ("src/app.py", "app", False),
        ("src/__init__.py", "", True),
        ("lib/src/app.py", "lib.src.app", False),
    ],
)
def test_source(path: str, module: str, *, package: bool) -> None:
    found = source(path)
    assert (found.module, found.package) == (module, package)


def test_only_core_files_are_checked() -> None:
    assert findings("import os\n", "src/app/shell.py") == ()
    assert findings("import os\n", "src/app/corex.py") == ()
    assert findings("import os\n", "src/app/core.py") == (
        f"1:1: PUR001 the core imports `os`; {IMPORTS}",
    )


@pytest.mark.parametrize(
    "code",
    [
        "import json\nimport collections.abc\nfrom typing import cast\n",
        "from ordered import FrozenList\n",
        "import ast\nimport tomllib\nfrom urllib.parse import quote\n",
        "from pathlib import PurePosixPath, PureWindowsPath, PurePath\n",
        "from tokenize import COMMENT, TokenError, generate_tokens\n",
        "from app.core import other\nfrom . import sibling\nfrom .x import y\n",
        "import app.core.other\n",
    ],
)
def test_pure_imports(code: str) -> None:
    assert findings(code) == ()


@pytest.mark.parametrize(
    ("code", "module"),
    [
        ("import os\n", "os"),
        ("import urllib.request\n", "urllib.request"),
        ("from pathlib import Path\n", "pathlib"),
        ("from pathlib import PurePath, Path\n", "pathlib"),
        ("import pathlib\n", "pathlib"),
        ("import tokenize\n", "tokenize"),
        ("from .. import shell\n", "app"),
        ("from ..shell import run\n", "app.shell"),
        ("from app import shell\n", "app"),
        ("import app\n", "app"),
        ("import httpx\n", "httpx"),
        ("import collectionsx\n", "collectionsx"),
    ],
)
def test_impure_imports(code: str, module: str) -> None:
    assert findings(code) == (
        f"1:1: PUR001 the core imports `{module}`; {IMPORTS}",
    )


def test_relative_imports_from_a_package() -> None:
    assert findings("from . import x\n", "src/app/core/__init__.py") == ()
    assert findings("from .. import x\n", "src/app/core/__init__.py") == (
        f"1:1: PUR001 the core imports `app`; {IMPORTS}",
    )


@pytest.mark.parametrize(
    "name",
    [
        "open",
        "input",
        "eval",
        "exec",
        "compile",
        "__import__",
        "breakpoint",
        "exit",
        "quit",
        "help",
        "globals",
    ],
)
def test_effect_builtins(name: str) -> None:
    assert findings(f"x = {name}\n") == (
        f"1:5: PUR002 the core uses the builtin `{name}`; keep I/O at the boundary",
    )


def test_assigning_a_builtin_name_is_not_a_use() -> None:
    assert findings("open = 1\nprint(x)\n") == ()


@pytest.mark.parametrize(
    ("code", "taken"),
    [
        ("def f(x: Callable[[], int]) -> None: ...\n", "Callable"),
        ("def f(*, x: Iterable[int]) -> None: ...\n", "Iterable"),
        ("def f(x, /, y: typing.Iterator[int]) -> None: ...\n", "Iterator"),
        ("def f(*x: Generator) -> None: ...\n", "Generator"),
        ("def f(**x: IO[str]) -> None: ...\n", "IO"),
        ("def f(x: 'type[int]') -> None: ...\n", "type"),
        ("def f[T: AsyncIterable[int]](x: T) -> None: ...\n", "AsyncIterable"),
        ("def __init__(x: Awaitable[int]) -> None: ...\n", "Awaitable"),
    ],
)
def test_functions_take_only_data(code: str, taken: str) -> None:
    name = code.split("(", 1)[0].split()[1].split("[", 1)[0]
    assert findings(code) == (
        f"1:1: PUR003 `{name}` takes `{taken}`; {ONLY_DATA}",
    )


def test_classes_and_fields_take_only_data() -> None:
    code = (
        "class Engine[T: Callable[[], int]]:\n"
        "    clock: Callable[[], int]\n"
        "    _cache: Callable[[], int]\n"
        "    def run(self, f: Coroutine) -> None: ...\n"
        "    def _hidden(self, f: Callable) -> None: ...\n"
        "class _Private:\n"
        "    clock: Callable[[], int]\n"
        "x: Callable[[], int] = f\n"
    )
    assert findings(code) == (
        f"1:1: PUR003 `Engine` takes `Callable`; {ONLY_DATA}",
        f"2:5: PUR003 `clock` takes `Callable`; {ONLY_DATA}",
        f"4:5: PUR003 `run` takes `Coroutine`; {ONLY_DATA}",
    )


def test_ports_defined_in_the_core() -> None:
    texts = FrozenOrderedDict({
        "pyproject.toml": PYPROJECT,
        "src/app/core/ports.py": (
            "class Store(Protocol): ...\n"
            "class Repo(abc.ABC): ...\n"
            "class Meta(metaclass=ABCMeta): ...\n"
            "class Data(Base, metaclass=Other): ...\n"
        ),
        "src/app/core/use.py": (
            "def a(s: Store, r: 'Repo') -> None: ...\n"
            "def b(m: Sequence[Meta], d: Data) -> None: ...\n"
        ),
    })
    outcome = run(
        ("src/app/core/ports.py", "src/app/core/use.py"), Inputs(texts)
    )
    assert tuple(outcome.lines) == (
        f"src/app/core/use.py:1:1: PUR003 `a` takes `Store`; {ONLY_DATA}",
        f"src/app/core/use.py:1:1: PUR003 `a` takes `Repo`; {ONLY_DATA}",
        f"src/app/core/use.py:2:1: PUR003 `b` takes `Meta`; {ONLY_DATA}",
        "Found 3 issues",
    )


def test_each_forbidden_type_is_reported_once() -> None:
    code = "def f(a: Callable, b: Callable, c: Iterable) -> Callable: ...\n"
    assert findings(code) == (
        f"1:1: PUR003 `f` takes `Callable`; {ONLY_DATA}",
        f"1:1: PUR003 `f` takes `Iterable`; {ONLY_DATA}",
    )


def test_async_anywhere_in_the_core() -> None:
    code = "async def _f() -> None: ...\ndef g() -> None:\n    async def h() -> None: ...\n"
    assert findings(code) == (
        "1:1: PUR003 `_f` is async",
        "3:5: PUR003 `h` is async",
    )


def test_findings_sort_by_position() -> None:
    code = "x = open\nimport os\n"
    assert tuple(finding.split(" ")[1] for finding in findings(code)) == (
        "PUR002",
        "PUR001",
    )


def skips(*pairs: tuple[str, str]) -> str:
    return f"--skips={json.dumps([list(pair) for pair in pairs])}"


@pytest.mark.parametrize(
    ("rule", "glob", "kept"),
    [
        ("PUR001", "src/app/core/m.py", ("PUR002",)),
        ("PUR001:httpx", "src/app/core/*.py", ("PUR001", "PUR002")),
        ("PUR001:os", "src/app/core/*.py", ("PUR001", "PUR002")),
        ("PUR001:attrs", "src/app/core/*.py", ("PUR001", "PUR001", "PUR002")),
        ("PUR001:httpx", "other.py", ("PUR001", "PUR001", "PUR002")),
        ("PUR002", "src/**", ("PUR001", "PUR001")),
        ("PUR002:open", "src/**", ("PUR001", "PUR001", "PUR002")),
    ],
)
def test_skips(rule: str, glob: str, kept: Sequence[str]) -> None:
    code = "import httpx.client\nimport os\nx = open\n"
    found = findings(code, "src/app/core/m.py", skips((rule, glob)))
    assert tuple(finding.split(" ")[1] for finding in found) == kept


def test_summary() -> None:
    texts = FrozenOrderedDict({
        "pyproject.toml": PYPROJECT,
        "src/app/core/m.py": "import os\n",
    })
    outcome = run(("src/app/core/m.py",), Inputs(texts))
    assert outcome.lines[-1] == "Found 1 issues"
    assert outcome.status == 1
    clean = run(
        ("src/app/core/m.py",), Inputs(texts | {"src/app/core/m.py": ""})
    )
    assert tuple(clean.lines) == ("All checks passed",)
    assert clean.status == 0


def test_unparseable_string_annotations_are_skipped() -> None:
    assert findings("def f(x: 'not valid(', y: 'Callable') -> None: ...\n") == (
        f"1:1: PUR003 `f` takes `Callable`; {ONLY_DATA}",
    )


def test_both_variadic_parameters_are_read() -> None:
    assert findings("def f(*a: Callable, **k: Iterable) -> None: ...\n") == (
        f"1:1: PUR003 `f` takes `Callable`; {ONLY_DATA}",
        f"1:1: PUR003 `f` takes `Iterable`; {ONLY_DATA}",
    )


def test_deep_relative_imports_stay_in_the_core() -> None:
    assert findings("from .. import x\n", "src/app/core/sub/deep/m.py") == ()


def test_mangled_names_are_private() -> None:
    code = "class A:\n    def __hidden(self, f: Callable) -> None: ...\n"
    assert findings(code) == ()


def test_a_bad_string_annotation_does_not_hide_the_rest() -> None:
    assert findings("def f(x: Mapping['bad(', Callable]) -> None: ...\n") == (
        f"1:1: PUR003 `f` takes `Callable`; {ONLY_DATA}",
    )


def test_syntax_errors_name_the_file() -> None:
    texts = FrozenOrderedDict({
        "pyproject.toml": PYPROJECT,
        "src/app/core/m.py": "def (:\n",
    })
    with pytest.raises(SyntaxError) as error:
        _ = run(("src/app/core/m.py",), Inputs(texts))
    assert error.value.filename == "src/app/core/m.py"
