import ast
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
lazy from collections.abc import Iterator


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    advice: str


UNFROZEN_DATACLASS = Rule("IMM001", "dataclass is not frozen=True")
MUTABLE_ANNOTATION = Rule(
    "IMM002",
    "in a parameter or field; use Sequence, Mapping, an Ordered type from ordered, or FrozenList, FrozenOrderedSet or FrozenOrderedDict",
)
MUTABLE_GLOBAL = Rule(
    "IMM003",
    "mutable module-level value; use a tuple, FrozenList or FrozenOrderedDict",
)
HASH_ORDERED_SET = Rule(
    "IMM004", "iterates in hash order, which changes per process"
)
UNORDERED_ANNOTATION = Rule(
    "IMM005",
    "promises no order; use OrderedSet or OrderedCollection from ordered, or Container for membership only",
)
UNNAMED_COLLECTION = Rule("IMM006", "has a name in ordered")
UNORDERED_TYPES = frozenset({
    "AbstractSet",
    "Collection",
    "FrozenSet",
    "Set",
    "frozenset",
    "set",
})
NAMED_COLLECTIONS = MappingProxyType({
    "MappingProxyType": "FrozenOrderedDict[K, V]",
    "frozendict": "FrozenOrderedDict[K, V]",
})
SET_CONSTRUCTORS = frozenset({"set", "frozenset"})
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
MUTABLE_VALUES = (ast.List, ast.Dict, ast.ListComp, ast.DictComp)
MUTABLE_CONSTRUCTORS = frozenset({"list", "dict", "bytearray"})


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


def every_annotation(tree: ast.Module) -> Iterator[ast.expr]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from filter(
                None,
                (
                    *(
                        parameter.annotation
                        for parameter in parameters(node.args)
                    ),
                    node.returns,
                ),
            )
        if (
            isinstance(node, ast.AnnAssign)
            and name_of(node.target) != "__slots__"
        ):
            yield node.annotation
        if isinstance(node, ast.TypeAlias):
            yield node.value
        if isinstance(node, ast.TypeVar) and node.bound is not None:
            yield node.bound


def annotation_nodes(
    annotation: ast.expr, anchor: ast.expr | None = None
) -> Iterator[tuple[ast.expr, ast.expr]]:
    for node in ast.walk(annotation):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                parsed = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                continue
            yield from annotation_nodes(parsed, anchor or node)
        elif isinstance(node, ast.expr):
            yield node, anchor or node


def is_homogeneous_tuple(node: ast.expr) -> bool:
    match node:
        case ast.Subscript(
            value=base, slice=ast.Tuple(elts=[_, ast.Constant(value=last)])
        ):
            return name_of(base) == "tuple" and last is Ellipsis
        case _:
            return False


def hash_ordered_sets(tree: ast.Module) -> Iterator[Finding]:
    rule = HASH_ORDERED_SET
    for node in ast.walk(tree):
        if not isinstance(node, ast.expr):
            continue
        built = (
            "a set literal"
            if isinstance(node, ast.Set)
            else "a set comprehension"
            if isinstance(node, ast.SetComp)
            else f"`{name_of(node.func)}()`"
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in SET_CONSTRUCTORS
            else ""
        )
        if built:
            message = f"{built} {rule.advice}; use FrozenOrderedSet"
            yield Finding(node.lineno, node.col_offset, rule, message)


def unordered_annotations(tree: ast.Module) -> Iterator[Finding]:
    for annotation in every_annotation(tree):
        for node, place in annotation_nodes(annotation):
            name = (
                name_of(node)
                if isinstance(node, ast.Name | ast.Attribute)
                else ""
            )
            if name in UNORDERED_TYPES:
                rule = UNORDERED_ANNOTATION
                message = f"`{name}` {rule.advice}"
                yield Finding(place.lineno, place.col_offset, rule, message)
            elif name in NAMED_COLLECTIONS or is_homogeneous_tuple(node):
                rule = UNNAMED_COLLECTION
                wanted = NAMED_COLLECTIONS.get(name, "FrozenList[T]")
                spelled = name or "tuple[T, ...]"
                message = f"`{spelled}` {rule.advice}; use {wanted}"
                yield Finding(place.lineno, place.col_offset, rule, message)


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
        *hash_ordered_sets(tree),
        *unordered_annotations(tree),
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
