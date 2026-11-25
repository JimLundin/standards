import pytest
from ordered import FrozenList, FrozenOrderedDict

from checks.core.comments import Comment, Item, comments, is_source, sources
from checks.core.exceptions import Issue, load
from checks.core.suppressions import suppressions


def found(
    file: str, text: str, *, library: bool = False
) -> FrozenList[Comment]:
    return FrozenList(comments(file, text, library=library))


@pytest.mark.parametrize(
    ("language", "file", "expected"),
    [
        ("python", "a.py", True),
        ("python", "a.pyw", True),
        ("python", "a.pyi", False),
        ("rust", "a.rs", True),
        ("rust", "a.py", False),
        ("typescript", "a.ts", True),
        ("typescript", "a.tsx", True),
        ("typescript", "a.mts", True),
        ("typescript", "a.cts", True),
        ("typescript", "a.js", True),
        ("typescript", "a.jsx", True),
        ("typescript", "a.mjs", True),
        ("typescript", "a.json", False),
        ("go", "a.go", False),
    ],
)
def test_is_source(language: str, file: str, *, expected: bool) -> None:
    assert is_source(language, file) is expected


def test_python_comments_and_docstrings() -> None:
    text = (
        '"""Module."""\n'
        "x = '# not a comment'  # a comment\n"
        "class A:\n"
        "    '''Class.'''\n"
        "    async def f(self):\n"
        '        """Method."""\n'
        "        y = 1\n"
        '        "not a docstring"\n'
        "# last\n"
    )
    assert found("a.py", text) == (
        Comment(1, "docstring", '"""Module."""'),
        Comment(2, "line", "# a comment"),
        Comment(4, "docstring", "'''Class.'''"),
        Comment(6, "docstring", '"""Method."""'),
        Comment(9, "line", "# last"),
    )


def test_python_that_does_not_parse_has_no_docstrings() -> None:
    assert found("a.py", '"""Doc."""\nx = = 1\ny = 2  # c\n') == (
        Comment(3, "line", "# c"),
    )


def test_rust_strings_hold_no_comments() -> None:
    text = (
        'let s = "// not a comment"; // real\n'
        'let r = r#"/* not a comment */"#; /* block */\n'
        "let c = '/'; let b = b\"// no\";\n"
    )
    assert found("a.rs", text) == (
        Comment(1, "line", "// real", precedes="let_declaration"),
        Comment(2, "block", "/* block */", precedes="let_declaration"),
    )


RUST_DOCS = """//! The crate.
/// A public function.
#[inline]
pub fn a() {}
/** A crate function. */
pub(crate) fn b() {}
/// A private struct.
struct C {
    /// A public field.
    pub d: u8,
}
/// A public trait.
pub trait E {
    /// A trait method.
    fn f();
}
/// A public enum.
pub enum G {
    /// A variant.
    H,
}
"""


def test_rust_doc_comments_name_their_item_and_its_visibility() -> None:
    assert found("a.rs", RUST_DOCS, library=True) == (
        Comment(
            1, "doc", "//! The crate.", Item("source_file", "", 1, public=True)
        ),
        Comment(
            2,
            "doc",
            "/// A public function.",
            Item("function_item", "a", 4, public=True),
        ),
        Comment(
            5,
            "doc",
            "/** A crate function. */",
            Item("function_item", "b", 6, public=False),
        ),
        Comment(
            7,
            "doc",
            "/// A private struct.",
            Item("struct_item", "C", 8, public=False),
        ),
        Comment(
            9,
            "doc",
            "/// A public field.",
            Item("field_declaration", "d", 10, public=True),
        ),
        Comment(
            12,
            "doc",
            "/// A public trait.",
            Item("trait_item", "E", 13, public=True),
        ),
        Comment(
            14,
            "doc",
            "/// A trait method.",
            Item("function_signature_item", "f", 15, public=True),
        ),
        Comment(
            17,
            "doc",
            "/// A public enum.",
            Item("enum_item", "G", 18, public=True),
        ),
        Comment(
            19,
            "doc",
            "/// A variant.",
            Item("enum_variant", "H", 20, public=True),
        ),
    )


def test_rust_doc_comments_of_a_binary_are_not_public() -> None:
    assert all(
        comment.item is not None and not comment.item.public
        for comment in found("a.rs", RUST_DOCS, library=False)
    )


def test_rust_inner_doc_comment_documents_its_module() -> None:
    text = "pub mod m {\n    //! The module.\n}\nmod n {\n    //! Private.\n}\n"
    assert found("a.rs", text, library=True) == (
        Comment(
            2, "doc", "//! The module.", Item("mod_item", "m", 1, public=True)
        ),
        Comment(
            5, "doc", "//! Private.", Item("mod_item", "n", 4, public=False)
        ),
    )


@pytest.mark.parametrize(
    "literal",
    [
        '"// not a comment"',
        "'/* not a comment */'",
        "`// not ${a} a comment */`",
        "/\\/\\/ not a comment/",
    ],
)
def test_typescript_literals_hold_no_comments(literal: str) -> None:
    text = f"const a = {literal}; // real\n"
    assert found("a.tsx", text) == (Comment(1, "line", "// real"),)


def test_typescript_comment_kinds() -> None:
    text = "/** Doc. */\nconst a = <div>{/* block */}</div>;\n/**/\n"
    assert found("a.tsx", text) == (
        Comment(1, "doc", "/** Doc. */"),
        Comment(2, "block", "/* block */"),
        Comment(3, "block", "/**/"),
    )


def test_a_lint_disable_inside_a_typescript_string_is_no_suppression() -> None:
    texts = FrozenOrderedDict({
        "a.ts": 'const a = "// eslint-disable";\n// eslint-disable\n'
    })
    assert tuple(
        suppressions("typescript", sources("typescript", texts), load(None))
    ) == (
        Issue(
            "a.ts:2",
            (
                "`// eslint-disable` silences oxlint; fix: change the code so"
                " oxlint passes, or, if the rule can't apply, an exception for"
                " that rule with its reason"
            ),
        ),
    )


def test_a_typescript_type_assertion_is_no_comment() -> None:
    text = "const x = 1;\nconst n = <number>x; // real\nconst m = 2;\n"
    assert found("a.ts", text) == (Comment(2, "line", "// real"),)


def test_a_python_shebang_is_no_comment() -> None:
    assert found("a.py", "#!/usr/bin/env python\nx = 1  # c\n") == (
        Comment(2, "line", "# c"),
    )


def test_a_rust_comment_names_what_it_precedes() -> None:
    text = (
        "fn f() {\n"
        "    // SAFETY: one\n"
        "    // and two\n"
        "    unsafe { g() }\n"
        "    // SAFETY: three\n"
        "    let x = unsafe { g() };\n"
        "    /* SAFETY: four */\n"
        "    let y =\n"
        "        unsafe { g() };\n"
        "    // five\n"
        "    g();\n"
        "}\n"
    )
    assert FrozenList(
        (comment.line, comment.precedes) for comment in found("a.rs", text)
    ) == (
        (2, "unsafe_block"),
        (3, "unsafe_block"),
        (5, "unsafe_block"),
        (7, "let_declaration"),
        (10, "expression_statement"),
    )
