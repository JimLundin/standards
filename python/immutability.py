import ast
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
lazy from collections.abc import Iterator


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    advice: str


UNFROZEN_DATACLASS = Rule("IMM001", "dataclass is not frozen=True")
MUTABLE_ANNOTATION = Rule(
    "IMM002", "in a parameter or field; use Sequence, Mapping or frozenset"
)
MUTABLE_GLOBAL = Rule(
    "IMM003", "mutable module-level value; use tuple, frozenset or a Mapping"
)
MUTABLE_TYPES = frozenset({
    "list",
    "dict",
    "set",
    "bytearray",
    "MutableSequence",
    "MutableMapping",
    "MutableSet",
    "List",
    "Dict",
    "Set",
    "DefaultDict",
    "OrderedDict",
    "Counter",
    "Deque",
    "defaultdict",
    "deque",
})
MUTABLE_VALUES = (
    ast.List,
    ast.Dict,
    ast.Set,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
)
MUTABLE_CONSTRUCTORS = frozenset({"list", "dict", "set", "bytearray"})


@dataclass(frozen=True, slots=True)
class Finding:
    line: int
    column: int
    rule: Rule
    message: str


def name_of(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return name_of(node.func)
    return ""


def is_unfrozen_dataclass(decorator: ast.expr) -> bool:
    if name_of(decorator) != "dataclass":
        return False
    if not isinstance(decorator, ast.Call):
        return True
    return not any(
        keyword.arg == "frozen"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in decorator.keywords
    )


def mutable_type(annotation: ast.expr) -> ast.expr | None:
    return next(
        (
            node
            for node in ast.walk(annotation)
            if isinstance(node, ast.Name | ast.Attribute)
            and name_of(node) in MUTABLE_TYPES
        ),
        None,
    )


def is_mutable_value(value: ast.expr | None) -> bool:
    return isinstance(value, MUTABLE_VALUES) or (
        isinstance(value, ast.Call)
        and name_of(value.func) in MUTABLE_CONSTRUCTORS
    )


def parameters(arguments: ast.arguments) -> tuple[ast.arg, ...]:
    return (
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *filter(None, (arguments.vararg, arguments.kwarg)),
    )


def annotations(tree: ast.Module) -> Iterator[ast.expr]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from (
                parameter.annotation
                for parameter in parameters(node.args)
                if parameter.annotation is not None
            )
        if isinstance(node, ast.ClassDef):
            yield from (
                statement.annotation
                for statement in node.body
                if isinstance(statement, ast.AnnAssign)
            )


def unfrozen_dataclasses(tree: ast.Module) -> Iterator[Finding]:
    rule = UNFROZEN_DATACLASS
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            yield from (
                Finding(
                    decorator.lineno, decorator.col_offset, rule, rule.advice
                )
                for decorator in node.decorator_list
                if is_unfrozen_dataclass(decorator)
            )


def mutable_annotations(tree: ast.Module) -> Iterator[Finding]:
    rule = MUTABLE_ANNOTATION
    for annotation in annotations(tree):
        found = mutable_type(annotation)
        if found is not None:
            message = f"mutable type `{name_of(found)}` {rule.advice}"
            yield Finding(found.lineno, found.col_offset, rule, message)


def mutable_globals(tree: ast.Module) -> Iterator[Finding]:
    rule = MUTABLE_GLOBAL
    yield from (
        Finding(statement.lineno, statement.col_offset, rule, rule.advice)
        for statement in tree.body
        if isinstance(statement, ast.Assign | ast.AnnAssign)
        and is_mutable_value(statement.value)
    )


def skipped(
    finding: Finding, path: str, skips: tuple[tuple[str, str], ...]
) -> bool:
    return any(
        code == finding.rule.code and PurePosixPath(path).full_match(glob)
        for code, glob in skips
    )


def check(path: str, skips: tuple[tuple[str, str], ...]) -> tuple[Finding, ...]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
    findings = (
        *unfrozen_dataclasses(tree),
        *mutable_annotations(tree),
        *mutable_globals(tree),
    )
    return tuple(
        finding
        for finding in sorted(findings, key=lambda f: (f.line, f.column))
        if not skipped(finding, path, skips)
    )


def describe(path: str, finding: Finding) -> str:
    rule = finding.rule
    location = f"{path}:{finding.line}:{finding.column + 1}"
    return f"{location}: {rule.code} {finding.message}"


def report(arguments: tuple[str, ...]) -> tuple[str, ...]:
    skips = tuple(
        (code, glob)
        for argument in arguments
        if argument.startswith("--skip=")
        for code, _, glob in (argument.removeprefix("--skip=").partition(":"),)
    )
    paths = tuple(
        argument for argument in arguments if not argument.startswith("--")
    )
    return tuple(
        describe(path, finding)
        for path in paths
        for finding in check(path, skips)
    )


def main() -> int:
    lines = report(tuple(sys.argv[1:]))
    summary = f"Found {len(lines)} issues" if lines else "All checks passed"
    output = "".join(f"{line}\n" for line in (*lines, summary))
    _ = sys.stdout.write(output)
    return 1 if lines else 0


if __name__ == "__main__":
    raise SystemExit(main())
