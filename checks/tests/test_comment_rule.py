import json
lazy from collections.abc import Mapping

import pytest
from ordered import FrozenList

from checks.core.policy import request, run
from checks.core.values import Inputs
from tests.helpers import entry, inputs, lines

STD = "C:/standards"
ROOT = "/work"
RESHAPE = (
    "fix: name, type or restructure the code so it needs none,"
    " or, if it explains what we can't reshape, a `comment` exception with"
    " its reason"
)
METADATA = json.dumps({
    "workspace_root": ROOT,
    "packages": [
        {
            "name": "app",
            "targets": [
                {"kind": ["lib"], "src_path": f"{ROOT}/src/lib.rs"},
                {"kind": ["bin"], "src_path": f"{ROOT}/src/main.rs"},
                {"kind": ["bin"], "src_path": f"{ROOT}/src/bin/tool/main.rs"},
            ],
        }
    ],
})
OPTION = "--metadata=/logs/metadata.json"


def checked(
    language: str, texts: Mapping[str, str], *options: str
) -> FrozenList[str]:
    files = FrozenList(path for path in texts if path != "exceptions.toml")
    found = run((language, STD, *options, *files), inputs(texts))
    return lines(found)


def rust(texts: Mapping[str, str]) -> FrozenList[str]:
    return checked("rust", {**texts, "/logs/metadata.json": METADATA}, OPTION)


def failed(*places: str, why: str = "comment") -> FrozenList[str]:
    return FrozenList((
        *(f"{place}: {why}; {RESHAPE}" for place in places),
        f"Found {len(places)} issues",
    ))


@pytest.mark.parametrize(
    ("language", "file", "text", "why"),
    [
        ("python", "a.py", "x = 1\n# note\n", "comment"),
        ("python", "a.py", 'def f():\n    """Note."""\n', "docstring"),
        ("rust", "a.rs", "fn f() {}\n// note\n", "comment"),
        ("rust", "a.rs", "fn f() {}\n/* note */\n", "comment"),
        ("typescript", "a.ts", "const a = 1;\n// note\n", "comment"),
        ("typescript", "a.ts", "const a = 1;\n/** note */\n", "JSDoc comment"),
    ],
)
def test_a_comment_fails_by_file_and_line_with_the_fix(
    language: str, file: str, text: str, why: str
) -> None:
    assert checked(language, {file: text}) == failed(f"{file}:2", why=why)


@pytest.mark.parametrize(
    ("language", "file", "text"),
    [
        ("rust", "a.rs", 'const A: &str = "// not a comment";\n'),
        ("rust", "a.rs", 'const A: &str = r#"// not a comment"#;\n'),
        ("typescript", "a.ts", 'const a = "// not a comment";\n'),
        ("typescript", "a.ts", "const a = `// not ${b} a comment`;\n"),
        ("typescript", "a.ts", "const a = /\\/\\/ not a comment/;\n"),
    ],
)
def test_a_comment_marker_inside_a_literal_passes(
    language: str, file: str, text: str
) -> None:
    assert checked(language, {file: text}) == ("All checks passed",)


DOCUMENTED = (
    "/// Public.\npub fn a() {}\n"
    "/// Crate.\npub(crate) fn b() {}\n"
    "/// Private.\nfn c() {}\n"
)


def test_a_doc_comment_passes_only_on_a_public_item_of_a_library() -> None:
    assert rust({"src/lib.rs": DOCUMENTED, "src/m.rs": DOCUMENTED}) == failed(
        "src/lib.rs:3",
        "src/lib.rs:5",
        "src/m.rs:3",
        "src/m.rs:5",
        why="doc comment on an item that isn't public in a library",
    )


OUTSIDE = "doc comment outside a library"


@pytest.mark.parametrize(
    "file", ["src/main.rs", "src/bin/tool/main.rs", "src/bin/tool/args.rs"]
)
def test_a_doc_comment_of_a_binary_target_fails(file: str) -> None:
    assert rust({"src/lib.rs": "", file: "/// Public.\npub fn a() {}\n"}) == (
        failed(f"{file}:1", why=OUTSIDE)
    )


def test_a_doc_comment_outside_every_library_fails() -> None:
    texts = {"tests/it.rs": "/// Public.\npub fn a() {}\n"}
    assert rust(texts) == failed("tests/it.rs:1", why=OUTSIDE)
    assert checked("rust", texts) == failed("tests/it.rs:1", why=OUTSIDE)


SAFE = (
    "fn f() {\n"
    "    // SAFETY: g has no preconditions\n"
    "    // beyond its signature.\n"
    "    unsafe { g() };\n"
    "    // SAFETY: g has no preconditions.\n"
    "    let x = unsafe { g() };\n"
    "    // SAFETY: g has no preconditions.\n"
    "    h(x);\n"
    "    // also\n"
    "    // SAFETY: g has no preconditions.\n"
    "    unsafe { g() };\n"
    "}\n"
)


def test_a_safety_comment_passes_only_directly_before_an_unsafe_block() -> None:
    assert checked("rust", {"a.rs": SAFE}) == failed(
        "a.rs:7", "a.rs:9", "a.rs:10"
    )


HEADER = "// SPDX-License-Identifier: MIT\n// Copyright 2026 Someone\n"


@pytest.mark.parametrize(
    ("file", "text"),
    [
        ("a.rs", HEADER + "fn f() {}\n"),
        ("a.ts", HEADER + "const a = 1;\n"),
        ("a.py", "#!/usr/bin/env python\n# Copyright 2026 Someone\nx = 1\n"),
    ],
)
def test_a_licence_header_passes(file: str, text: str) -> None:
    language = {"rs": "rust", "ts": "typescript", "py": "python"}
    checks = checked(language[file.rpartition(".")[2]], {file: text})
    assert checks == ("All checks passed",)


def test_a_licence_header_further_down_fails() -> None:
    text = "fn f() {}\n" + HEADER
    assert checked("rust", {"a.rs": text}) == failed("a.rs:2", "a.rs:3")


def test_a_licence_naming_comment_after_the_first_block_fails() -> None:
    text = "// note\n\n" + HEADER
    assert checked("rust", {"a.rs": text}) == failed(
        "a.rs:1", "a.rs:3", "a.rs:4"
    )


@pytest.mark.parametrize(
    ("language", "file", "text", "marker"),
    [
        ("python", "a.py", "x = 1  # noqa\n", "# noqa"),
        ("typescript", "a.ts", "// eslint-disable\n", "// eslint-disable"),
        ("typescript", "a.ts", "// oxlint-disable\n", "// oxlint-disable"),
    ],
)
def test_a_suppression_is_reported_once_as_a_suppression(
    language: str, file: str, text: str, marker: str
) -> None:
    assert checked(language, {file: text}) == (
        f"{file}:1: suppression `{marker}`; add an entry to exceptions.toml instead",
        "Found 1 issues",
    )


def test_a_biome_ignore_suppresses_nothing_so_it_is_reported_as_a_comment() -> (
    None
):
    text = "const a = 1;\n// biome-ignore lint: x\n"
    assert checked("typescript", {"a.ts": text}) == failed("a.ts:2")


def test_a_comment_exception_passes_every_comment_of_its_path() -> None:
    texts = {
        "exceptions.toml": entry("src/*.py", "comment"),
        "src/a.py": '"""Doc."""\n# note\n',
        "b.py": "# note\n",
    }
    assert checked("python", texts) == failed("b.py:1")


def test_a_comment_exception_without_a_reason_fails() -> None:
    texts = {
        "exceptions.toml": entry("a.py", "comment", " "),
        "a.py": "x = 1\n",
    }
    assert checked("python", texts) == (
        "exceptions.toml: exception 1 needs a path, a rule and a reason",
        "Found 1 issues",
    )


def test_a_comment_exception_is_a_known_rule_in_every_language() -> None:
    for language, file in (
        ("python", "a.py"),
        ("rust", "a.rs"),
        ("typescript", "a.ts"),
    ):
        texts = {"exceptions.toml": entry(file, "comment"), file: "// x\n"}
        assert checked(language, texts) == ("All checks passed",)


def test_a_licence_header_ends_at_the_first_line_holding_code() -> None:
    text = "# SPDX-License-Identifier: MIT\nimport os  # x\n"
    assert checked("python", {"a.py": text}) == failed("a.py:2")


def test_a_docstring_naming_copyright_is_no_licence_header() -> None:
    text = '"""Copyright 2026 Someone."""\n'
    assert checked("python", {"a.py": text}) == failed(
        "a.py:1", why="docstring"
    )


def test_a_python_type_comment_fails_naming_annotations() -> None:
    text = "def f(a):\n    # type: (int) -> None\n    return a\n"
    assert checked("python", {"a.py": text}) == (
        "a.py:2: type comment; fix: use an annotation",
        "Found 1 issues",
    )


DIRECTIVE = (
    "triple-slash directive; fix: name it in `compilerOptions.types`"
    " in tsconfig.json"
)


def test_a_triple_slash_directive_fails_naming_compiler_options_types() -> None:
    text = '/// <reference types="x" />\nconst a = 1;\n'
    assert checked("typescript", {"a.ts": text}) == (
        f"a.ts:1: {DIRECTIVE}",
        "Found 1 issues",
    )


def test_a_doc_comment_inside_a_macro_body_fails() -> None:
    text = "macro_rules! m {\n    () => {\n        /// Doc.\n        pub fn a() {}\n    };\n}\n"
    assert rust({"src/lib.rs": text}) == failed(
        "src/lib.rs:3", why="doc comment on no item, as in a macro body"
    )


def test_request_reads_the_metadata() -> None:
    paths = request(("rust", STD, OPTION, "src/lib.rs"), Inputs()).paths
    assert "/logs/metadata.json" in paths
    assert OPTION not in paths
