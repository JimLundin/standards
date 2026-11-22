import json
import tomllib
lazy from collections.abc import Mapping

from ordered import FrozenList, FrozenOrderedDict

from checks.core.rust_core import (
    PLAIN,
    POINTERS,
    TESTS_ONLY,
    UNCONDITIONAL,
    clippy_request,
    clippy_run,
    request,
    run,
    toml_value,
)
from checks.core.values import Inputs, Outcome, Request
from tests.helpers import entry, inputs

ROOT = "C:\\work"
CORE_ROOT = "core/src/lib.rs"
SHELL_ROOT = "io/src/lib.rs"


def package(
    name: str, kind: str, layer: str | None = None
) -> Mapping[str, object]:
    return {
        "name": name,
        "targets": [
            {"kind": [kind], "src_path": f"{ROOT}\\{name}\\src\\lib.rs"},
            {"kind": ["test"], "src_path": f"{ROOT}\\{name}\\tests\\it.rs"},
        ],
        "metadata": None if layer is None else {"standards": {"layer": layer}},
    }


METADATA = json.dumps({
    "workspace_root": ROOT,
    "packages": [
        package("core", "lib"),
        package("io", "lib", layer="shell"),
        package("app", "bin"),
    ],
})
FILES = (CORE_ROOT, "core/src/a.rs", "core/README.md", SHELL_ROOT)
ARGUMENTS = ("m.json", "d.jsonl", *FILES)
CLEAN = "#![no_std]\n"


def diagnostic(
    message: str,
    *,
    level: str = "warning",
    code: str | None = "clippy::disallowed_types",
    owner: str = "core",
    file: str | None = CORE_ROOT,
) -> str:
    return json.dumps({
        "reason": "compiler-message",
        "target": {"src_path": f"{ROOT}\\{owner}\\src\\lib.rs"},
        "message": {
            "level": level,
            "message": message,
            "code": None if code is None else {"code": code},
            "spans": [{"file_name": file, "line_start": 7, "is_primary": True}]
            if file is not None
            else [],
        },
    })


def checked(
    *diagnostics: str,
    root: str = CLEAN,
    other: str = "",
    exceptions: str | None = None,
) -> Outcome:
    texts = {
        "m.json": METADATA,
        "d.jsonl": "\n".join(diagnostics),
        CORE_ROOT: root,
        "core/src/a.rs": other,
    }
    if exceptions is not None:
        texts |= {"exceptions.toml": exceptions}
    return run(ARGUMENTS, inputs(texts))


def test_request_reads_the_core_sources_once_the_metadata_is_known() -> None:
    fixed = ("exceptions.toml", "m.json", "d.jsonl")
    assert request(ARGUMENTS, Inputs()) == Request(FrozenList(fixed))
    assert request(ARGUMENTS, inputs({"m.json": METADATA})) == Request(
        FrozenList((*fixed, CORE_ROOT, "core/src/a.rs"))
    )


def test_a_clean_core_passes() -> None:
    assert checked(json.dumps({"reason": "build-finished"}), "noise") == (
        Outcome(FrozenList(("no_std: core",)))
    )
    empty = json.dumps({"workspace_root": ROOT, "packages": []})
    assert run(("m.json", "d.jsonl"), inputs({"m.json": empty})) == Outcome(
        FrozenList(("no libraries",))
    )


def test_the_root_declares_no_std_unconditionally() -> None:
    assert checked(root="#![cfg_attr(not(test), no_std)]\n").status == 0
    assert checked(root="// #![no_std]\n#![no_std] // pure\n").status == 0
    for root in ("", '#![cfg_attr(not(target_os = "none"), no_std)]\n'):
        assert checked(root=root).lines == (
            f"{CORE_ROOT}:1: {UNCONDITIONAL}",
            "Found 1 issues",
        )


def test_std_is_for_tests_only() -> None:
    allowed = "#[cfg(test)]\n\nextern crate std;\n#[cfg(test)] extern crate std;\n// extern crate std;\n"
    assert checked(other=allowed).status == 0
    gated = '#[cfg(feature = "std")]\nextern crate std as host;\n'
    assert checked(other=gated).lines == (
        f"core/src/a.rs:2: {TESTS_ONLY}",
        "Found 1 issues",
    )


def test_core_libraries_use_no_pointers() -> None:
    box = diagnostic("use of a disallowed type `alloc::boxed::Box`")
    assert checked(box, box).lines == (
        f"{CORE_ROOT}:7: uses `alloc::boxed::Box`; {PLAIN}",
        "Found 1 issues",
    )
    ignored = (
        diagnostic("use of a disallowed type `alloc::rc::Rc`", owner="io"),
        diagnostic("use of a disallowed type `core::cell::Cell`"),
        diagnostic("use of `alloc::sync::Arc`", code="clippy::other"),
        diagnostic("use of a disallowed type", code=None),
        diagnostic("use of a disallowed type `alloc::sync::Arc`", file=None),
    )
    assert checked(*ignored).status == 0


def test_a_box_exception_covers_a_file() -> None:
    arc = diagnostic("use of a disallowed type `alloc::sync::Arc`")
    assert checked(arc, exceptions=entry(CORE_ROOT, "box")).status == 0
    assert checked(arc, exceptions=entry(CORE_ROOT, "api")).status == 1


def test_build_errors_are_reported() -> None:
    error = diagnostic(
        "can't find crate for `std`", level="error", code="E0463"
    )
    assert checked(error).lines == (
        f"{CORE_ROOT}:7: can't find crate for `std`",
        "Found 1 issues",
    )
    assert checked(diagnostic("aborting", level="error", file=None)).status == 0
    unsourced = diagnostic(
        "can't find crate for `std`", level="error", file="clippy.toml"
    )
    assert checked(unsourced).lines[0] == (
        f"{CORE_ROOT}:1: can't find crate for `std`"
    )


def test_the_core_config_adds_the_pointers_to_the_base() -> None:
    base = 'msrv = "1.90"\ndisallowed-types = ["core::cell::Cell", { path = "alloc::rc::Rc", reason = "mine" }]\n'
    assert clippy_request(("c.toml", "out.toml"), Inputs()) == Request(
        FrozenList(("c.toml",))
    )
    written = clippy_run(
        ("c.toml", "out.toml"), inputs({"c.toml": base})
    ).writes["out.toml"]
    config = tomllib.loads(written)
    assert config["msrv"] == "1.90"
    assert config["disallowed-types"] == [
        "core::cell::Cell",
        {"path": "alloc::rc::Rc", "reason": "mine"},
        *(
            {"path": pointer, "reason": PLAIN}
            for pointer in POINTERS
            if pointer != "alloc::rc::Rc"
        ),
    ]
    fresh = clippy_run(("c.toml", "out.toml"), Inputs()).writes
    assert tomllib.loads(fresh["out.toml"])["disallowed-types"] == [
        {"path": pointer, "reason": PLAIN} for pointer in POINTERS
    ]


def test_toml_values_round_trip() -> None:
    value: FrozenOrderedDict[str, object] = FrozenOrderedDict({
        "on": True,
        "off": False,
        "count": 3,
        "ratio": 0.5,
        "name": 'tab\t"quoted" ü',
        "empty": FrozenOrderedDict[str, object](),
        "nested": [FrozenOrderedDict[str, object]({"a": [1, 2]})],
    })
    document = f"value = {toml_value(value)}\n"
    assert tomllib.loads(document)["value"] == {
        "on": True,
        "off": False,
        "count": 3,
        "ratio": 0.5,
        "name": 'tab\t"quoted" ü',
        "empty": {},
        "nested": [{"a": [1, 2]}],
    }


def test_findings_sort_by_line() -> None:
    text = "\nextern crate std;" + "\n" * 9 + "extern crate std;\n"
    assert checked(other=text).lines == (
        f"core/src/a.rs:2: {TESTS_ONLY}",
        f"core/src/a.rs:11: {TESTS_ONLY}",
        "Found 2 issues",
    )
