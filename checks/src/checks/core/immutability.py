import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.exceptions import EXCEPTIONS, Exceptions, exceptions_in
from checks.core.values import Inputs, Outcome, Request, summarized

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


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
UNORDERED_TYPES = FrozenOrderedSet((
    "AbstractSet",
    "Collection",
    "FrozenSet",
    "Set",
    "frozenset",
    "set",
))
NAMED_COLLECTIONS = FrozenOrderedDict({
    "MappingProxyType": "FrozenOrderedDict[K, V]",
    "frozendict": "FrozenOrderedDict[K, V]",
})
ITEM_AND_ELLIPSIS = 2
SET_CONSTRUCTORS = FrozenOrderedSet(("set", "frozenset"))
MUTABLE_TYPES = FrozenOrderedSet((
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
))
MUTABLE_VALUES = (ast.List, ast.Dict, ast.ListComp, ast.DictComp)
MUTABLE_CONSTRUCTORS = FrozenOrderedSet(("list", "dict", "bytearray"))


@dataclass(frozen=True, slots=True)
class Finding:
    line: int
    column: int
    rule: Rule
    message: str


def name_of(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case ast.Call(func=func):
            return name_of(func)
        case _:
            return None


def is_unfrozen_dataclass(decorator: ast.expr) -> bool:
    if name_of(decorator) != "dataclass":
        return False
    match decorator:
        case ast.Call(keywords=keywords):
            return not any(
                keyword.arg == "frozen"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in keywords
            )
        case _:
            return True


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
        and isinstance(value.func, ast.Name)
        and value.func.id in MUTABLE_CONSTRUCTORS
    )


def parameters(arguments: ast.arguments) -> FrozenList[ast.arg]:
    return FrozenList((
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *filter(None, (arguments.vararg, arguments.kwarg)),
    ))


def annotations(tree: ast.Module) -> Iterator[ast.expr]:
    for node in ast.walk(tree):
        match node:
            case (
                ast.FunctionDef(args=arguments)
                | ast.AsyncFunctionDef(args=arguments)
            ):
                yield from (
                    parameter.annotation
                    for parameter in parameters(arguments)
                    if parameter.annotation is not None
                )
            case ast.ClassDef(body=body):
                yield from (
                    statement.annotation
                    for statement in body
                    if isinstance(statement, ast.AnnAssign)
                )
            case _:
                pass


def node_annotations(node: ast.AST) -> Iterator[ast.expr]:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        yield from filter(
            None,
            (
                *(parameter.annotation for parameter in parameters(node.args)),
                node.returns,
            ),
        )
    if isinstance(node, ast.AnnAssign) and name_of(node.target) != "__slots__":
        yield node.annotation
    if isinstance(node, ast.TypeAlias):
        yield node.value
    if isinstance(node, ast.TypeVar) and node.bound is not None:
        yield node.bound


def every_annotation(tree: ast.Module) -> Iterator[ast.expr]:
    for node in ast.walk(tree):
        yield from node_annotations(node)


def unquoted(text: str) -> Iterator[ast.expr]:
    try:
        parsed = ast.parse(text, mode="eval")
    except SyntaxError:
        return
    yield parsed.body


def annotation_nodes(
    annotation: ast.expr, anchor: ast.expr | None = None
) -> Iterator[tuple[ast.expr, ast.expr]]:
    for node in ast.walk(annotation):
        yield from annotation_node(node, anchor)


def annotation_node(
    node: ast.AST, anchor: ast.expr | None
) -> Iterator[tuple[ast.expr, ast.expr]]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        for parsed in unquoted(node.value):
            yield from annotation_nodes(parsed, anchor or node)
    elif isinstance(node, ast.expr):
        yield node, anchor or node


def is_homogeneous_tuple(node: ast.expr) -> bool:
    match node:
        case ast.Subscript(value=value, slice=ast.Tuple(elts=elements)):
            return (
                name_of(value) == "tuple"
                and len(elements) == ITEM_AND_ELLIPSIS
                and isinstance(last := elements[-1], ast.Constant)
                and last.value is Ellipsis
            )
        case _:
            return False


def membership_sets(tree: ast.Module) -> FrozenOrderedSet[int]:
    return FrozenOrderedSet(
        id(right)
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        for index, operator in enumerate(node.ops)
        if isinstance(operator, ast.In | ast.NotIn)
        for right in (node.comparators[index],)
        if isinstance(right, ast.Set)
    )


def built_set(node: ast.expr) -> str:
    match node:
        case ast.Set():
            return "a set literal"
        case ast.SetComp():
            return "a set comprehension"
        case ast.Call(func=ast.Name(id=name) as func) if (
            name in SET_CONSTRUCTORS
        ):
            return f"`{name_of(func)}()`"
        case _:
            return ""


def hash_ordered_sets(tree: ast.Module) -> Iterator[Finding]:
    rule = HASH_ORDERED_SET
    tested = membership_sets(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.expr) or id(node) in tested:
            continue
        built = built_set(node)
        if built:
            message = f"{built} {rule.advice}; use FrozenOrderedSet"
            yield Finding(node.lineno, node.col_offset, rule, message)


def unordered_annotation(node: ast.expr, place: ast.expr) -> Finding | None:
    name = name_of(node) if isinstance(node, ast.Name | ast.Attribute) else None
    if name is not None and name in UNORDERED_TYPES:
        rule = UNORDERED_ANNOTATION
        message = f"`{name}` {rule.advice}"
    elif name is not None and name in NAMED_COLLECTIONS:
        rule = UNNAMED_COLLECTION
        message = f"`{name}` {rule.advice}; use {NAMED_COLLECTIONS[name]}"
    elif is_homogeneous_tuple(node):
        rule = UNNAMED_COLLECTION
        message = f"`tuple[T, ...]` {rule.advice}; use FrozenList[T]"
    else:
        return None
    return Finding(place.lineno, place.col_offset, rule, message)


def unordered_annotations(tree: ast.Module) -> Iterator[Finding]:
    yield from filter(
        None,
        (
            unordered_annotation(node, place)
            for annotation in every_annotation(tree)
            for node, place in annotation_nodes(annotation)
        ),
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


def check(path: str, text: str, exceptions: Exceptions) -> FrozenList[Finding]:
    tree = ast.parse(text, filename=path)
    findings = (
        *unfrozen_dataclasses(tree),
        *mutable_annotations(tree),
        *mutable_globals(tree),
        *hash_ordered_sets(tree),
        *unordered_annotations(tree),
    )
    return FrozenList(
        finding
        for finding in sorted(findings, key=lambda f: (f.line, f.column))
        if not exceptions.covers(finding.rule.code, path)
    )


def describe(path: str, finding: Finding) -> str:
    rule = finding.rule
    location = f"{path}:{finding.line}:{finding.column + 1}"
    return f"{location}: {rule.code} {finding.message}"


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((EXCEPTIONS, *arguments)))


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    exceptions = exceptions_in(inputs)
    return summarized(
        FrozenList(
            describe(path, finding)
            for path in arguments
            for finding in check(path, inputs.texts[path], exceptions)
        )
    )
