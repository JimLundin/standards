import ast
from dataclasses import dataclass
from io import StringIO
from tokenize import COMMENT, TokenError, generate_tokens
from typing import TYPE_CHECKING, Literal

import tree_sitter_rust
import tree_sitter_typescript
from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet
from tree_sitter import Language, Node, Parser

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

type Kind = Literal["line", "block", "doc", "docstring"]

SOURCES = FrozenOrderedDict({
    "python": FrozenList((".py", ".pyw")),
    "rust": FrozenList((".rs",)),
    "typescript": FrozenList((
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        ".js",
        ".jsx",
        ".mjs",
    )),
})
RUST = Language(tree_sitter_rust.language())
TYPESCRIPT = Language(tree_sitter_typescript.language_typescript())
TSX = Language(tree_sitter_typescript.language_tsx())
WITHOUT_JSX = FrozenList((".ts", ".mts", ".cts"))
RUST_COMMENTS = FrozenOrderedSet(("line_comment", "block_comment"))
DOC_MARKERS = FrozenOrderedSet((
    "outer_doc_comment_marker",
    "inner_doc_comment_marker",
))
BODIES = FrozenOrderedSet(("declaration_list", "block"))
ATTRIBUTES = FrozenOrderedSet(("attribute_item", "inner_attribute_item"))
SKIPPED = FrozenOrderedSet((*RUST_COMMENTS, "attribute_item"))
PUBLIC_MEMBERS = FrozenOrderedDict({
    "enum_variant_list": "enum_item",
    "declaration_list": "trait_item",
})
STATEMENTS = FrozenOrderedSet(("expression_statement", "let_declaration"))
UNSAFE = "unsafe_block"
NO_LIBRARIES: FrozenOrderedSet[str] = FrozenOrderedSet()
DOCUMENTED = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True, slots=True)
class Item:
    kind: str
    name: str
    line: int
    public: bool


@dataclass(frozen=True, slots=True)
class Comment:
    line: int
    kind: Kind
    text: str
    item: Item | None = None
    precedes: str = ""


@dataclass(frozen=True, slots=True)
class Attribute:
    line: int
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class Source:
    text: str
    library: bool
    comments: FrozenList[Comment]
    attributes: FrozenList[Attribute]


def is_source(language: str, file: str) -> bool:
    return file.endswith(tuple(SOURCES.get(language, FrozenList())))


def python_docstrings(text: str) -> Iterator[Comment]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return
    lines = text.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, DOCUMENTED) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            start, end = first.lineno - 1, (first.end_lineno or first.lineno)
            source = "\n".join(lines[start:end])
            yield Comment(first.lineno, "docstring", source.strip())


def python_comments(text: str) -> Iterator[Comment]:
    try:
        tokens = FrozenList(generate_tokens(StringIO(text).readline))
    except SyntaxError, TokenError:
        return
    yield from (
        Comment(token.start[0], "line", token.string.strip())
        for token in tokens
        if token.type == COMMENT
        and not (token.start == (1, 0) and token.string.startswith("#!"))
    )


def node_text(node: Node) -> str:
    return (node.text or b"").decode()


def named_children(node: Node) -> Iterator[Node]:
    yield node
    for child in node.named_children:
        yield from named_children(child)


def has_doc_marker(node: Node) -> bool:
    return any(child.type in DOC_MARKERS for child in node.named_children)


def declared_public(node: Node) -> bool:
    return any(
        child.type == "visibility_modifier" and node_text(child) == "pub"
        for child in node.named_children
    )


def is_public(node: Node) -> bool:
    if node.type == "source_file" or declared_public(node):
        return True
    parent = node.parent
    owner = parent.parent if parent is not None else None
    return (
        parent is not None
        and owner is not None
        and PUBLIC_MEMBERS.get(parent.type) == owner.type
        and is_public(owner)
    )


def documented(comment: Node) -> Node | None:
    if comment.parent is not None and comment.parent.type == "token_tree":
        return None
    inner = any(
        child.type == "inner_doc_comment_marker"
        for child in comment.named_children
    )
    if inner:
        parent = comment.parent
        if parent is not None and parent.type in BODIES:
            return parent.parent
        return parent
    sibling = comment.next_named_sibling
    while sibling is not None and sibling.type in SKIPPED:
        sibling = sibling.next_named_sibling
    return sibling


def opens_unsafe(statement: Node) -> bool:
    return any(
        node.type == UNSAFE
        and node.start_point.row == statement.start_point.row
        for node in named_children(statement)
    )


def preceded(comment: Node) -> str:
    sibling = comment.next_named_sibling
    while sibling is not None and sibling.type in RUST_COMMENTS:
        sibling = sibling.next_named_sibling
    if sibling is None:
        return ""
    if sibling.type in STATEMENTS and opens_unsafe(sibling):
        return UNSAFE
    return sibling.type


def item_of(node: Node, *, library: bool) -> Item:
    name = node.child_by_field_name("name")
    return Item(
        node.type,
        "" if name is None else node_text(name),
        node.start_point.row + 1,
        library and is_public(node),
    )


def rust_comment(node: Node, *, library: bool) -> Comment:
    line, text = node.start_point.row + 1, node_text(node).strip()
    if not has_doc_marker(node):
        kind = "line" if node.type == "line_comment" else "block"
        return Comment(line, kind, text, precedes=preceded(node))
    item = documented(node)
    found = None if item is None else item_of(item, library=library)
    return Comment(line, "doc", text, found)


def rust_attribute(node: Node) -> Attribute:
    attribute = next(
        child for child in node.named_children if child.type == "attribute"
    )
    path, *rest = attribute.named_children
    arguments = "".join(
        node_text(child) for child in rest if child.type == "token_tree"
    )
    return Attribute(node.start_point.row + 1, node_text(path), arguments)


def rust_source(text: str, *, library: bool) -> Source:
    tree = Parser(RUST).parse(text.encode())
    nodes = FrozenList(named_children(tree.root_node))
    return Source(
        text,
        library,
        FrozenList(
            rust_comment(node, library=library)
            for node in nodes
            if node.type in RUST_COMMENTS
        ),
        FrozenList(
            rust_attribute(node) for node in nodes if node.type in ATTRIBUTES
        ),
    )


def typescript_kind(text: str) -> Kind:
    if text.startswith("//"):
        return "line"
    return "doc" if text.startswith("/**") and text != "/**/" else "block"


def typescript_comments(file: str, text: str) -> Iterator[Comment]:
    grammar = TYPESCRIPT if file.endswith(tuple(WITHOUT_JSX)) else TSX
    tree = Parser(grammar).parse(text.encode())
    for node in named_children(tree.root_node):
        if node.type == "comment":
            body = node_text(node).strip()
            yield Comment(node.start_point.row + 1, typescript_kind(body), body)


def parse(file: str, text: str, *, library: bool = False) -> Source:
    if is_source("rust", file):
        return rust_source(text, library=library)
    found: FrozenList[Comment] = FrozenList()
    if is_source("python", file):
        found = FrozenList(
            sorted(
                (*python_comments(text), *python_docstrings(text)),
                key=lambda comment: comment.line,
            )
        )
    elif is_source("typescript", file):
        found = FrozenList(typescript_comments(file, text))
    return Source(text, library, found, FrozenList())


def comments(
    file: str, text: str, *, library: bool = False
) -> Iterator[Comment]:
    yield from parse(file, text, library=library).comments


def sources(
    language: str,
    texts: Mapping[str, str],
    libraries: FrozenOrderedSet[str] = NO_LIBRARIES,
) -> FrozenOrderedDict[str, Source]:
    return FrozenOrderedDict(
        (file, parse(file, text, library=file in libraries))
        for file, text in texts.items()
        if is_source(language, file)
    )
