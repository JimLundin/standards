import ast
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

PURE_MODULES = frozenset({
    "__future__",
    "abc",
    "base64",
    "binascii",
    "bisect",
    "calendar",
    "cmath",
    "collections",
    "contextlib",
    "copy",
    "dataclasses",
    "datetime",
    "decimal",
    "difflib",
    "enum",
    "fnmatch",
    "fractions",
    "functools",
    "graphlib",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "ipaddress",
    "itertools",
    "json",
    "keyword",
    "math",
    "numbers",
    "operator",
    "random",
    "re",
    "shlex",
    "statistics",
    "string",
    "struct",
    "textwrap",
    "types",
    "typing",
    "unicodedata",
    "urllib.parse",
    "uuid",
    "zlib",
})
EFFECT_BUILTINS = frozenset({
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "exit",
    "globals",
    "help",
    "input",
    "open",
    "quit",
})
EFFECT_TYPES = frozenset({
    "AsyncGenerator",
    "AsyncIterable",
    "AsyncIterator",
    "Awaitable",
    "BinaryIO",
    "Callable",
    "Coroutine",
    "Generator",
    "IO",
    "Iterable",
    "Iterator",
    "TextIO",
    "Type",
    "type",
})
PORT_BASES = frozenset({"ABC", "Protocol"})
LAYER = re.compile(r"[\w.]+")
IMPORTS = "it may import itself, pure standard modules and a PUR001:<module> exception"
ONLY_DATA = "the core's public API takes only data"


@dataclass(frozen=True, slots=True)
class Source:
    module: str
    package: bool = False


@dataclass(frozen=True, slots=True)
class Finding:
    line: int
    column: int
    rule: str
    message: str


def table(value: object) -> Mapping[str, object]:
    if isinstance(value, dict):
        return cast("Mapping[str, object]", value)
    return MappingProxyType({})


def entries(value: object) -> tuple[object, ...]:
    if isinstance(value, list):
        return tuple(cast("Iterable[object]", value))
    return ()


def core_modules(pyproject: Path) -> tuple[str, ...]:
    if not pyproject.is_file():
        return ()
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    contracts = entries(
        table(table(data.get("tool")).get("importlinter")).get("contracts")
    )
    return tuple(
        f"{container}.{name}"
        for contract in contracts
        if table(contract).get("type") == "layers"
        for layers in (entries(table(contract).get("layers")),)
        if layers
        for container in entries(table(contract).get("containers"))
        for name in cast("list[str]", LAYER.findall(str(layers[-1])))
    )


def source(path: str) -> Source:
    parts = PurePosixPath(path).with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    package = bool(parts) and parts[-1] == "__init__"
    return Source(".".join(parts[:-1] if package else parts), package=package)


def within(module: str, roots: Iterable[str]) -> bool:
    return any(
        module == root or module.startswith(f"{root}.") for root in roots
    )


def resolve(node: ast.ImportFrom, origin: Source) -> str:
    if node.level == 0:
        return node.module or ""
    base = origin.module if origin.package else origin.module.rpartition(".")[0]
    for _ in range(node.level - 1):
        base = base.rpartition(".")[0]
    return ".".join(part for part in (base, node.module) if part)


def imported(
    tree: ast.Module, origin: Source
) -> Iterator[tuple[ast.stmt, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from ((node, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node, resolve(node, origin)


def import_findings(
    tree: ast.Module, origin: Source, cores: tuple[str, ...]
) -> Iterator[Finding]:
    yield from (
        Finding(
            node.lineno,
            node.col_offset,
            f"PUR001:{name}",
            f"the core imports `{name}`; {IMPORTS}",
        )
        for node, name in imported(tree, origin)
        if not within(name, (*PURE_MODULES, *cores))
    )


def builtin_findings(tree: ast.Module) -> Iterator[Finding]:
    yield from (
        Finding(
            node.lineno,
            node.col_offset,
            "PUR002",
            f"the core uses the builtin `{node.id}`; keep I/O at the boundary",
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in EFFECT_BUILTINS
    )


def base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def ports(tree: ast.Module) -> frozenset[str]:
    return frozenset(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and (
            any(base_name(base) in PORT_BASES for base in node.bases)
            or any(
                keyword.arg == "metaclass"
                and base_name(keyword.value) == "ABCMeta"
                for keyword in node.keywords
            )
        )
    )


def names(annotation: ast.expr | None) -> Iterator[str]:
    if annotation is None:
        return
    for node in ast.walk(annotation):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                yield from names(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                continue
        name = base_name(node) if isinstance(node, ast.expr) else ""
        if name:
            yield name


def is_public(name: str) -> bool:
    return not name.startswith("_") or (
        name.startswith("__") and name.endswith("__")
    )


def parameters(node: ast.FunctionDef) -> Iterator[ast.expr | None]:
    arguments = node.args
    every = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    yield from (argument.annotation for argument in every)
    for extra in (arguments.vararg, arguments.kwarg):
        if extra is not None:
            yield extra.annotation


def bounds(node: ast.FunctionDef | ast.ClassDef) -> Iterator[ast.expr | None]:
    for parameter in node.type_params:
        if isinstance(parameter, ast.TypeVar):
            yield parameter.bound


def api_inputs(
    body: Iterable[ast.stmt], *, in_class: bool
) -> Iterator[tuple[str, ast.stmt, Iterator[ast.expr | None]]]:
    for node in body:
        if isinstance(node, ast.FunctionDef) and is_public(node.name):
            yield node.name, node, iter((*parameters(node), *bounds(node)))
        elif isinstance(node, ast.ClassDef) and is_public(node.name):
            yield node.name, node, bounds(node)
            yield from api_inputs(node.body, in_class=True)
        elif (
            in_class
            and isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and is_public(node.target.id)
        ):
            yield node.target.id, node, iter((node.annotation,))


def api_findings(
    tree: ast.Module, local_ports: frozenset[str]
) -> Iterator[Finding]:
    forbidden = EFFECT_TYPES | local_ports
    for name, node, annotations in api_inputs(tree.body, in_class=False):
        taken = dict.fromkeys(
            found
            for annotation in annotations
            for found in names(annotation)
            if found in forbidden
        )
        yield from (
            Finding(
                node.lineno,
                node.col_offset,
                "PUR003",
                f"`{name}` takes `{found}`; {ONLY_DATA}",
            )
            for found in taken
        )
    yield from (
        Finding(
            node.lineno, node.col_offset, "PUR003", f"`{node.name}` is async"
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    )


def covers(rule: str, found: str) -> bool:
    code, _, module = found.partition(":")
    wanted, _, prefix = rule.partition(":")
    return wanted == code and (
        not prefix or (bool(module) and within(module, (prefix,)))
    )


def skipped(
    finding: Finding, path: str, skips: tuple[tuple[str, str], ...]
) -> bool:
    return any(
        covers(rule, finding.rule) and PurePosixPath(path).full_match(glob)
        for rule, glob in skips
    )


def check(
    trees: Mapping[str, ast.Module],
    cores: tuple[str, ...],
    skips: tuple[tuple[str, str], ...],
) -> Iterator[str]:
    local_ports = frozenset(
        name for tree in trees.values() for name in ports(tree)
    )
    for path, tree in trees.items():
        findings = (
            *import_findings(tree, source(path), cores),
            *builtin_findings(tree),
            *api_findings(tree, local_ports),
        )
        yield from (
            f"{path}:{finding.line}:{finding.column + 1}: {finding.rule.partition(':')[0]} {finding.message}"
            for finding in sorted(findings, key=lambda f: (f.line, f.column))
            if not skipped(finding, path, skips)
        )


def report(arguments: tuple[str, ...]) -> tuple[str, ...]:
    skips = tuple(
        (str(rule), str(glob))
        for argument in arguments
        if argument.startswith("--skips=")
        for pair in entries(
            cast("object", json.loads(argument.removeprefix("--skips=")))
        )
        for rule, glob in (entries(pair),)
    )
    cores = core_modules(Path("pyproject.toml"))
    trees = {
        path: ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
        for path in arguments
        if not path.startswith("--") and within(source(path).module, cores)
    }
    return tuple(check(trees, cores, skips))


def main() -> int:
    lines = report(tuple(sys.argv[1:]))
    summary = f"Found {len(lines)} issues" if lines else "All checks passed"
    output = "".join(f"{line}\n" for line in (*lines, summary))
    _ = sys.stdout.write(output)
    return 1 if lines else 0


if __name__ == "__main__":
    raise SystemExit(main())
