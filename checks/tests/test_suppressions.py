import pytest
from ordered import FrozenList, FrozenOrderedDict

from checks.core.comments import Attribute, parse, sources
from checks.core.exceptions import Exceptions, Issue, load
from checks.core.suppressions import (
    attribute_lints,
    markers,
    suppressions,
    used_attributes,
)
from tests.helpers import assert_each_names_the_fix

ALLOW = (
    " silences a lint; fix: change the code so the lint passes, or, if it"
    " can't apply, `#[expect]` it with an exception for the lint and its"
    " reason"
)


def silences(marker: str, tool: str) -> str:
    return (
        f"`{marker}` silences {tool}; fix: change the code so {tool} passes,"
        " or, if the rule can't apply, an exception for that rule with its"
        " reason"
    )


def found(
    language: str, texts: FrozenOrderedDict[str, str], exceptions: Exceptions
) -> FrozenList[Issue]:
    issues = FrozenList(
        suppressions(language, sources(language, texts), exceptions)
    )
    assert_each_names_the_fix(issues)
    return issues


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
    assert found("rust", texts, exceptions) == (
        Issue(
            "src/lib.rs:1",
            (
                "`#[expect(clippy::b)]` silences `clippy::b`; fix: change the code"
                " so `clippy::b` passes and drop it, or, if the lint can't apply,"
                " a `clippy::b` exception with its reason"
            ),
        ),
        Issue("src/lib.rs:3", f"`#[allow(dead_code)]`{ALLOW}"),
        Issue(
            "src/lib.rs:4",
            (
                "`#[mutants::skip]` hides code from cargo-mutants; fix: test the"
                " code so its mutants die, or, if they can't, a `mutation`"
                " exception with its reason"
            ),
        ),
        Issue(
            "src/lib.rs:5",
            (
                "`#[rustfmt::skip]` hides code from rustfmt; fix: drop it and let"
                " rustfmt format the code"
            ),
        ),
        Issue("src/lib.rs:6", f"`#[cfg_attr(test, allow(unused))]`{ALLOW}"),
    )


def test_python_and_typescript_suppressions_skip_other_files() -> None:
    texts = FrozenOrderedDict({
        "a.py": "x = 1  # noqa\n",
        "b.ts": "// oxlint-disable-next-line x\n",
        "c.txt": "# noqa\n",
    })
    assert found("python", texts, load(None)) == (
        Issue("a.py:1", silences("# noqa", "ruff")),
    )
    assert found("typescript", texts, load(None)) == (
        Issue("b.ts:1", silences("// oxlint-disable-next-line x", "oxlint")),
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
    assert found("python", texts, load(None)) == (
        Issue("a.py:1", silences("# noqa", "ruff")),
    )
    assert found("rust", texts, load(None)) == (
        Issue("b.rs:1", f"`#[allow(x)]`{ALLOW}"),
        Issue("c.rs:2", f"`#[allow(y)]`{ALLOW}"),
    )


def test_rust_attribute_lines_count_from_the_start() -> None:
    assert parse("a.rs", "\n\n#[allow(x)]\n").attributes == (
        Attribute(3, "allow", "(x)"),
    )


@pytest.mark.parametrize(
    ("file", "comment", "tool"),
    [
        ("a.py", "# noqa: E501", "ruff"),
        ("a.py", "# NOQA", "ruff"),
        ("a.py", "#ruff: noqa", "ruff"),
        ("a.py", "# type: ignore", "basedpyright"),
        ("a.py", "# basedpyright: ignore", "basedpyright"),
        ("a.py", "# pragma: no cover", "coverage"),
        ("a.py", "# pragma: no mutate", "mutmut"),
        ("a.py", "# fmt: skip", "ruff format"),
        ("a.py", "# isort: skip", "ruff"),
        ("a.ts", "// @ts-expect-error", "tsc"),
        ("a.ts", "// Stryker disable all", "Stryker"),
        ("a.ts", "/* c8 ignore next */", "coverage"),
        ("a.ts", "/* istanbul ignore next */", "coverage"),
        ("a.ts", "// eslint-disable no-console", "oxlint"),
        ("a.ts", "// prettier-ignore", "oxfmt"),
    ],
)
def test_a_suppression_names_the_tool_it_silences(
    file: str, comment: str, tool: str
) -> None:
    language = "python" if file.endswith(".py") else "typescript"
    texts = FrozenOrderedDict({file: f"x\n{comment}\n"})
    assert found(language, texts, load(None)) == (
        Issue(f"{file}:2", silences(comment, tool)),
    )
