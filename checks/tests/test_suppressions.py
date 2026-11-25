import pytest
from ordered import FrozenOrderedDict

from checks.core.comments import Attribute, parse, sources
from checks.core.exceptions import Issue, load
from checks.core.suppressions import (
    attribute_lints,
    markers,
    suppressions,
    used_attributes,
)

INSTEAD = "; add an entry to exceptions.toml instead"


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
    text = f"x = 1\ny = 2  {comment}  \n"
    assert tuple(markers("python", parse("a.py", text))) == ((2, comment),)


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
    assert tuple(markers("python", parse("a.py", text))) == ()


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
    assert tuple(markers("typescript", parse("a.ts", text))) == ((2, line),)


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
    assert tuple(markers("typescript", parse("a.ts", text))) == ((2, line),)


def test_typescript_markers_ignore_biome_ignore() -> None:
    text = "// biome-ignore lint: x\n/* biome-ignore lint: x */\n"
    assert tuple(markers("typescript", parse("a.ts", text))) == ()


def test_typescript_markers_need_a_comment() -> None:
    text = 'const a = "oxlint-disable";\n'
    assert tuple(markers("typescript", parse("a.ts", text))) == ()


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
    assert parse("a.rs", text).attributes == (
        Attribute(1, "no_std", ""),
        Attribute(2, "derive", "(Clone)"),
        Attribute(4, "expect", '( clippy::x, reason = "a (b)" )'),
        Attribute(5, "mutants::skip", ""),
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
    assert tuple(suppressions("rust", sources("rust", texts), exceptions)) == (
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
    assert tuple(
        suppressions("python", sources("python", texts), load(None))
    ) == (Issue("a.py:1", f"suppression `# noqa`{INSTEAD}"),)
    assert tuple(
        suppressions("typescript", sources("typescript", texts), load(None))
    ) == (
        Issue(
            "b.ts:1", f"suppression `// oxlint-disable-next-line x`{INSTEAD}"
        ),
    )


def test_used_attributes() -> None:
    texts = FrozenOrderedDict({
        "a.rs": RUST,
        "b.py": '#[expect(clippy::c, reason = "x")]',
    })
    assert tuple(used_attributes(sources("rust", texts))) == (
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
    assert tuple(
        suppressions("python", sources("python", texts), load(None))
    ) == (Issue("a.py:1", f"suppression `# noqa`{INSTEAD}"),)
    assert tuple(suppressions("rust", sources("rust", texts), load(None))) == (
        Issue("b.rs:1", f"#[allow(x)]{INSTEAD}"),
        Issue("c.rs:2", f"#[allow(y)]{INSTEAD}"),
    )


def test_rust_attribute_lines_count_from_the_start() -> None:
    assert parse("a.rs", "\n\n#[allow(x)]\n").attributes == (
        Attribute(3, "allow", "(x)"),
    )
