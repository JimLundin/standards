import pytest
from ordered import FrozenOrderedDict

from checks.core.exceptions import Issue, load
from checks.core.suppressions import (
    attribute_lints,
    is_source,
    python_markers,
    rust_attributes,
    suppressions,
    typescript_markers,
    used_attributes,
)

INSTEAD = "; add an entry to exceptions.toml instead"


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


@pytest.mark.parametrize(
    "comment",
    [
        "# noqa",
        "# noqa: E501",
        "#ruff: noqa",
        "# type: ignore",
        "# type:ignore[x]",
        "# pyright: ignore",
        "# basedpyright: ignore",
        "# pragma: no cover",
        "# pragma: no mutate",
        "# fmt: off",
        "# fmt: skip",
        "# isort: skip",
        "# NOQA",
    ],
)
def test_python_markers_find_suppressions(comment: str) -> None:
    assert tuple(python_markers(f"x = 1\ny = 2  {comment}  \n")) == (
        (2, comment),
    )


@pytest.mark.parametrize(
    "text",
    [
        'x = "# noqa"\n',
        "# noqanot\n",
        "# a plain comment\n",
        "# pragma: no branch\n",
        "x = (\n",
        "def f(:\n    pass\n",
    ],
)
def test_python_markers_ignore_other_text(text: str) -> None:
    assert tuple(python_markers(text)) == ()


@pytest.mark.parametrize(
    "line",
    [
        "/* @ts-ignore */",
        "// @ts-expect-error",
        "//@ts-nocheck",
        "// Stryker disable all",
        "// Stryker restore all",
        "/* c8 ignore next */",
        "/* istanbul ignore next */",
        "/* node:coverage ignore next */",
        "// prettier-ignore",
    ],
)
def test_typescript_markers(line: str) -> None:
    text = f"const a = 1;\n  {line}  \n"
    assert tuple(typescript_markers(text)) == ((2, line),)


@pytest.mark.parametrize("linter", ["oxlint", "eslint"])
@pytest.mark.parametrize(
    "form", ["disable", "enable", "disable-line", "disable-next-line"]
)
@pytest.mark.parametrize(
    ("opening", "closing"), [("// ", ""), ("/* ", " */")], ids=["line", "block"]
)
def test_typescript_markers_find_lint_disable_comments(
    linter: str, form: str, opening: str, closing: str
) -> None:
    line = f"{opening}{linter}-{form} no-console{closing}"
    text = f"const a = 1;\n  {line}  \n"
    assert tuple(typescript_markers(text)) == ((2, line),)


def test_typescript_markers_ignore_biome_ignore() -> None:
    text = "// biome-ignore lint: x\n/* biome-ignore lint: x */\n"
    assert tuple(typescript_markers(text)) == ()


def test_typescript_markers_need_a_comment() -> None:
    assert tuple(typescript_markers('const a = "oxlint-disable";\n')) == ()


def test_attribute_lints_drop_reasons() -> None:
    arguments = '(clippy::a, b , reason = "x, \\" y")'
    assert attribute_lints(arguments) == ("clippy::a", "b")
    assert attribute_lints("()") == ()


def test_rust_attributes() -> None:
    text = (
        "#![no_std]\n"
        "#[derive(Clone)]\n"
        "struct A;\n"
        '#[ expect ( clippy::x, reason = "a (b)" ) ]\n'
        "#[mutants::skip]\n"
    )
    assert tuple(rust_attributes(text)) == (
        (1, "no_std", ""),
        (2, "derive", "(Clone)"),
        (4, "expect", '( clippy::x, reason = "a (b)" )'),
        (5, "mutants::skip", ""),
    )


RUST = """#[expect(clippy::a, clippy::b, reason = "x")]
fn f() {}
#[allow(dead_code)]
#[mutants::skip]
#[rustfmt::skip]
#[cfg_attr(test, allow(unused))]
#[cfg_attr(test, derive(Debug))]
#[cfg_attr(feature = "skipping", inline)]
#[derive(Clone)]
"""


def test_rust_suppressions() -> None:
    texts = FrozenOrderedDict({"src/lib.rs": RUST, "Cargo.toml": "[x]"})
    exceptions = load(
        '[[exception]]\npath = "src/*.rs"\nrule = "clippy::a"\nreason = "r"\n'
    )
    assert tuple(suppressions("rust", texts, exceptions)) == (
        Issue("src/lib.rs:1", "#[expect(clippy::b)] is not in exceptions.toml"),
        Issue("src/lib.rs:3", f"#[allow(dead_code)]{INSTEAD}"),
        Issue("src/lib.rs:4", f"#[mutants::skip]{INSTEAD}"),
        Issue("src/lib.rs:5", f"#[rustfmt::skip]{INSTEAD}"),
        Issue("src/lib.rs:6", f"#[cfg_attr(test, allow(unused))]{INSTEAD}"),
    )


def test_python_and_typescript_suppressions_skip_other_files() -> None:
    texts = FrozenOrderedDict({
        "a.py": "x = 1  # noqa\n",
        "b.ts": "// oxlint-disable-next-line x\n",
        "c.txt": "# noqa\n",
    })
    assert tuple(suppressions("python", texts, load(None))) == (
        Issue("a.py:1", f"suppression `# noqa`{INSTEAD}"),
    )
    assert tuple(suppressions("typescript", texts, load(None))) == (
        Issue(
            "b.ts:1", f"suppression `// oxlint-disable-next-line x`{INSTEAD}"
        ),
    )


def test_used_attributes() -> None:
    texts = FrozenOrderedDict({
        "a.rs": RUST,
        "b.py": '#[expect(clippy::c, reason = "x")]',
    })
    assert tuple(used_attributes(texts)) == (
        ("a.rs", "clippy::a"),
        ("a.rs", "clippy::b"),
    )


def test_scanning_continues_past_other_files() -> None:
    texts = FrozenOrderedDict({
        "notes.txt": "# noqa\n",
        "a.py": "x = 1  # noqa\n",
        "b.rs": "#[allow(x)]\n",
        "c.rs": "\n#[allow(y)]\n",
    })
    assert tuple(suppressions("python", texts, load(None))) == (
        Issue("a.py:1", f"suppression `# noqa`{INSTEAD}"),
    )
    assert tuple(suppressions("rust", texts, load(None))) == (
        Issue("b.rs:1", f"#[allow(x)]{INSTEAD}"),
        Issue("c.rs:2", f"#[allow(y)]{INSTEAD}"),
    )


def test_rust_attribute_lines_count_from_the_start() -> None:
    assert tuple(rust_attributes("\n\n#[allow(x)]\n")) == ((3, "allow", "(x)"),)
