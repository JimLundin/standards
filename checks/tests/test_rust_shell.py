import json
lazy from collections.abc import Mapping, Sequence

import pytest
from ordered import FrozenList, FrozenOrderedDict

from checks.core.rust_shell import (
    Failure,
    Function,
    functions,
    measured,
    records,
    request,
    roots,
    roots_request,
    run,
    share_run,
    targets,
    typescript_records,
)
from checks.core.tools import request as tool_request
from checks.core.tools import run as tool_run
from checks.core.values import Inputs, Request, parse_json
from tests.helpers import entry

MOVE = "; move the decisions into the core"
ROOT = "C:\\work"


def target(path: str, *kinds: str) -> Mapping[str, object]:
    return {"kind": list(kinds), "src_path": f"{ROOT}\\{path}"}


def package(
    name: str, *items: Mapping[str, object], layer: str | None = None
) -> Mapping[str, object]:
    return {
        "name": name,
        "targets": list(items),
        "metadata": None if layer is None else {"standards": {"layer": layer}},
    }


APP = package(
    "app",
    target("src/main.rs", "bin"),
    target("src/lib.rs", "lib"),
    target("tests/it.rs", "test"),
    target("build.rs", "custom-build"),
)
IO = package("io", target("io/src/lib.rs", "rlib"), layer="shell")
METADATA = json.dumps({"workspace_root": ROOT, "packages": [APP, IO]})


def record(root: str, path: str, line: int, decisions: int) -> str:
    return json.dumps({
        "root": f"{ROOT}\\{root}",
        "path": f"{ROOT}\\{path}",
        "function": f"f{line}",
        "line": line,
        "decisions": decisions,
    })


def shell(path: str, line: int, decisions: int) -> str:
    return record("src/main.rs", path, line, decisions)


def core(path: str, line: int, decisions: int) -> str:
    return record("src/lib.rs", path, line, decisions)


def failure(path: str, error: str) -> str:
    return json.dumps({
        "root": f"{ROOT}\\src\\main.rs",
        "path": path,
        "error": error,
    })


def outcome(
    *lines: str, exceptions: str | None = None
) -> tuple[FrozenList[str], int, str]:
    texts = FrozenOrderedDict({"m.json": METADATA, "d.jsonl": "\n".join(lines)})
    if exceptions is not None:
        texts |= {"exceptions.toml": exceptions}
    result = run(("m.json", "d.jsonl", "files.txt"), Inputs(texts))
    return result.lines, result.status, result.writes["files.txt"]


def shared(
    *lines: str, exceptions: str | None = None
) -> tuple[FrozenList[str], int]:
    texts = FrozenOrderedDict({"m.json": METADATA, "d.jsonl": "\n".join(lines)})
    if exceptions is not None:
        texts |= {"exceptions.toml": exceptions}
    result = share_run(("m.json", "d.jsonl"), Inputs(texts))
    return result.lines, result.status


def test_requests_read_the_metadata_and_the_measures() -> None:
    assert roots_request(("m.json",), Inputs()) == Request(
        FrozenList(("m.json",))
    )
    assert request(("m.json", "d.jsonl", "files.txt"), Inputs()) == Request(
        FrozenList(("exceptions.toml", "m.json", "d.jsonl"))
    )


def test_binaries_libraries_and_shell_packages_are_measured() -> None:
    assert targets(parse_json(METADATA)) == {
        f"{ROOT}\\src/main.rs": True,
        f"{ROOT}\\src/lib.rs": False,
        f"{ROOT}\\io/src/lib.rs": True,
    }
    assert roots(
        ("m.json",), Inputs(FrozenOrderedDict({"m.json": METADATA}))
    ).lines == (
        f"{ROOT}\\src/main.rs",
        f"{ROOT}\\src/lib.rs",
        f"{ROOT}\\io/src/lib.rs",
    )
    assert roots(("m.json",), Inputs()).lines == ()


def test_measures_are_read_relative_to_the_workspace() -> None:
    roots_of = {f"{ROOT}\\src/main.rs": True}
    assert measured(shell("src/a.rs", 3, 2), roots_of, ROOT) == Function(
        "src/a.rs", 3, "f3", 2, in_shell=True
    )
    assert measured(core("src/a.rs", 3, 2), roots_of, ROOT) == Function(
        "src/a.rs", 3, "f3", 2, in_shell=False
    )
    assert measured(
        failure("C:/work/src/../x.rs", "line 1: expected `)`"), roots_of, ROOT
    ) == Failure("x.rs", "line 1: expected `)`")
    assert measured(failure("/elsewhere/x.rs", "gone"), roots_of, ROOT) == (
        Failure("/elsewhere/x.rs", "gone")
    )


def test_records_skip_other_lines_and_duplicates() -> None:
    lines = (
        "warning: something",
        shell("src/main.rs", 1, 1),
        shell("src/main.rs", 1, 1),
        core("src/lib.rs", 1, 2),
    )
    assert records(lines, parse_json(METADATA)) == (
        Function("src/main.rs", 1, "f1", 1, in_shell=True),
        Function("src/lib.rs", 1, "f1", 2, in_shell=False),
    )


def test_a_thin_shell_passes() -> None:
    lines, status, files = outcome(
        shell("src/main.rs", 1, 2),
        shell("src/io.rs", 1, 0),
        core("src/lib.rs", 1, 8),
        core("src/shared.rs", 1, 0),
        shell("src/shared.rs", 5, 0),
    )
    assert lines == ("shell makes 2 of 10 decisions",)
    assert status == 0
    assert files == "src/main.rs\nsrc/io.rs\n"


def test_shell_files_include_shell_libraries() -> None:
    lines, status, files = outcome(
        record("io/src/lib.rs", "io/src/lib.rs", 1, 1),
        record("io/src/lib.rs", "src/shared.rs", 1, 0),
        core("src/shared.rs", 1, 0),
        core("src/lib.rs", 1, 9),
    )
    assert lines == ("shell makes 1 of 10 decisions",)
    assert status == 0
    assert files == "io/src/lib.rs\n"


def test_no_shell() -> None:
    assert outcome(core("src/lib.rs", 1, 2)) == (("no shell",), 0, "")
    assert outcome() == (("no shell",), 0, "")


def test_complex_shell_functions_fail() -> None:
    lines, status, _ = outcome(
        shell("src/main.rs", 7, 3),
        shell("src/main.rs", 9, 2),
        record("io/src/lib.rs", "io/src/lib.rs", 4, 3),
        core("src/lib.rs", 4, 9),
    )
    assert lines == (
        f"src/main.rs:7: the shell function `f7` makes 3 decisions (limit 2){MOVE}",
        f"io/src/lib.rs:4: the shell function `f4` makes 3 decisions (limit 2){MOVE}",
        "Found 2 issues",
    )
    assert status == 1


def test_a_shell_exception_lifts_the_function_limit_for_its_file_only() -> None:
    lines, status, _ = outcome(
        shell("src/main.rs", 7, 3),
        shell("src/cli.rs", 9, 3),
        exceptions=entry("src/main.rs", "shell"),
    )
    assert lines == (
        f"src/cli.rs:9: the shell function `f9` makes 3 decisions (limit 2){MOVE}",
        "Found 1 issues",
    )
    assert status == 1


@pytest.mark.parametrize(
    "exceptions",
    [entry("src/*.rs", "api"), entry("other.rs", "shell"), "", None],
)
def test_other_exceptions_leave_the_function_limit(
    exceptions: str | None,
) -> None:
    lines, status, _ = outcome(
        shell("src/main.rs", 7, 3), exceptions=exceptions
    )
    assert lines[-1] == "Found 1 issues"
    assert status == 1


def test_unmeasured_files_fail_unless_excepted() -> None:
    broken = failure(f"{ROOT}\\src\\gen.rs", "No such file")
    lines, status, _ = outcome(broken, shell("src/main.rs", 1, 1))
    assert lines == (
        "src/gen.rs: cannot be measured: No such file",
        "Found 1 issues",
    )
    assert status == 1
    assert outcome(broken, exceptions=entry("src/gen.rs", "shell"))[:2] == (
        ("no shell",),
        0,
    )


def test_the_shell_share_applies_from_twenty_decisions() -> None:
    shell_lines = (shell("src/main.rs", line, 2) for line in range(3))
    lines, status = shared(*shell_lines, core("src/lib.rs", 1, 15))
    assert lines == (
        f"Cargo.toml: the shell makes 6 of 21 decisions (limit 25%){MOVE}",
        "Found 1 issues",
    )
    assert status == 1


def test_the_shell_share_boundaries() -> None:
    def share(functions: int, core_decisions: int) -> FrozenList[str]:
        shell_lines = tuple(
            shell("src/main.rs", line, 1) for line in range(functions)
        )
        return shared(*shell_lines, core("src/lib.rs", 1, core_decisions))[0]

    assert share(5, 15) == ("shell makes 5 of 20 decisions",)
    assert share(6, 14) == (
        f"Cargo.toml: the shell makes 6 of 20 decisions (limit 25%){MOVE}",
        "Found 1 issues",
    )
    assert share(6, 13) == ("shell makes 6 of 19 decisions",)


def test_a_shell_exception_on_cargo_toml_lifts_the_share_limit() -> None:
    shell_lines = (shell("src/main.rs", line, 2) for line in range(10))
    lines, status = shared(
        *shell_lines, exceptions=entry("Cargo.toml", "shell")
    )
    assert lines == ("shell makes 20 of 20 decisions",)
    assert status == 0


def test_an_api_exception_on_cargo_toml_leaves_the_share_limit() -> None:
    shell_lines = (shell("src/main.rs", line, 2) for line in range(10))
    lines, status = shared(*shell_lines, exceptions=entry("Cargo.toml", "api"))
    assert lines[0].startswith("Cargo.toml: the shell makes 20 of 20")
    assert status == 1


def test_the_package_check_leaves_the_share_to_the_project_s_unit() -> None:
    shell_lines = (shell("src/main.rs", line, 2) for line in range(10))
    lines, status, _ = outcome(*shell_lines)
    assert lines == ("shell makes 20 of 20 decisions",)
    assert status == 0


def compact(record: Mapping[str, object]) -> str:
    return json.dumps(record, separators=(",", ":"))


def test_typescript_measure_records_are_read() -> None:
    # Records as typescript-measure prints them, with the layer it adds.
    lines = (
        compact({
            "decisions": 3,
            "function": "View",
            "layer": "ui",
            "line": 2,
            "path": "packages/ui/src/view.tsx",
            "root": "packages/ui",
        }),
        compact({
            "error": "not in the project",
            "layer": "shell",
            "path": "packages/shell/src/gone.ts",
            "root": "packages/shell",
        }),
    )
    metadata = parse_json(
        json.dumps({"workspace_root": "/work", "packages": []})
    )
    assert records(lines, metadata) == (
        Function("packages/ui/src/view.tsx", 2, "View", 3, in_shell=True),
        Failure("packages/shell/src/gone.ts", "not in the project"),
    )


def test_a_typescript_api_record_is_not_a_function() -> None:
    lines = (
        compact({
            "api": "reaches `Promise`",
            "export": "promised",
            "layer": "core",
            "line": 3,
            "path": "packages/core/src/a.ts",
            "root": "packages/core",
        }),
        typescript("core", "packages/core/src/a.ts", 3, 0),
    )
    assert typescript_records(lines) == (
        Function("packages/core/src/a.ts", 3, "f3", 0, in_shell=False),
    )


def typescript(layer: str, path: str, line: int, decisions: int) -> str:
    return compact({
        "decisions": decisions,
        "function": f"f{line}",
        "layer": layer,
        "line": line,
        "path": path,
        "root": path.rsplit("/src/", 1)[0],
    })


def typescript_outcome(
    *lines: str, exceptions: str | None = None
) -> tuple[FrozenList[str], int, str]:
    texts = FrozenOrderedDict({"d.jsonl": "\n".join(lines)})
    if exceptions is not None:
        texts |= {"exceptions.toml": exceptions}
    result = tool_run(
        ("typescript-shell", "d.jsonl", "files.txt"), Inputs(texts)
    )
    return result.lines, result.status, result.writes["files.txt"]


def typescript_shared(
    *lines: str, exceptions: str | None = None
) -> tuple[FrozenList[str], int]:
    texts = FrozenOrderedDict({"d.jsonl": "\n".join(lines)})
    if exceptions is not None:
        texts |= {"exceptions.toml": exceptions}
    result = tool_run(("typescript-shell-share", "d.jsonl"), Inputs(texts))
    return result.lines, result.status


def test_typescript_requests_read_the_exceptions_and_the_measures() -> None:
    assert tool_request(
        ("typescript-shell", "d.jsonl", "files.txt"), Inputs()
    ) == Request(FrozenList(("exceptions.toml", "d.jsonl")))
    assert tool_request(
        ("typescript-shell-share", "d.jsonl"), Inputs()
    ) == Request(FrozenList(("exceptions.toml", "d.jsonl")))


def test_typescript_shell_and_ui_records_are_the_shell() -> None:
    lines = (
        typescript("shell", "packages/io/src/main.ts", 1, 1),
        typescript("ui", "packages/app/src/view.tsx", 2, 1),
        typescript("core", "packages/model/src/index.ts", 3, 1),
    )
    metadata = parse_json(json.dumps({"workspace_root": "/w", "packages": []}))
    assert [item.in_shell for item in functions(records(lines, metadata))] == [
        True,
        True,
        False,
    ]


# Each case is the decisions of the shell's functions and of the core's.
CASES = (
    ((2, 0), (8,)),
    ((3, 2, 3), (9,)),
    ((2, 2, 2), (15,)),
    ((1,) * 5, (15,)),
    ((1,) * 6, (14,)),
    ((1,) * 6, (13,)),
    ((), (4,)),
)


@pytest.mark.parametrize(("shell_counts", "core_counts"), CASES)
def test_typescript_records_get_the_verdicts_of_rust_records(
    shell_counts: Sequence[int], core_counts: Sequence[int]
) -> None:
    rust_lines = (
        *(
            shell(f"src/s{line}.rs", line, n)
            for line, n in enumerate(shell_counts)
        ),
        *(core("src/lib.rs", line, n) for line, n in enumerate(core_counts)),
    )
    # The UI shares the shell's side.
    layers = ("shell", "ui")
    typescript_lines = (
        *(
            typescript(
                layers[line % 2],
                f"packages/{layers[line % 2]}/src/s{line}.rs",
                line,
                n,
            )
            for line, n in enumerate(shell_counts)
        ),
        *(
            typescript("core", "packages/core/src/lib.rs", line, n)
            for line, n in enumerate(core_counts)
        ),
    )

    def renamed(found: FrozenList[str]) -> FrozenList[str]:
        return FrozenList(
            line.replace("src/s", "s").replace("Cargo.toml", "package.json")
            for line in found
        )

    def rust_shaped(found: FrozenList[str]) -> FrozenList[str]:
        return FrozenList(
            line.replace("packages/shell/src/s", "s").replace(
                "packages/ui/src/s", "s"
            )
            for line in found
        )

    rust_lines_found, rust_status, rust_files = outcome(*rust_lines)
    ts_lines_found, ts_status, ts_files = typescript_outcome(*typescript_lines)
    assert rust_shaped(ts_lines_found) == renamed(rust_lines_found)
    assert ts_status == rust_status
    assert len(ts_files.splitlines()) == len(rust_files.splitlines())
    rust_share, rust_share_status = shared(*rust_lines)
    ts_share, ts_share_status = typescript_shared(*typescript_lines)
    assert ts_share == renamed(rust_share)
    assert ts_share_status == rust_share_status


def test_a_typescript_shell_exception_lifts_the_function_limit_for_its_file() -> (
    None
):
    lines, status, files = typescript_outcome(
        typescript("ui", "packages/ui/src/view.tsx", 7, 3),
        typescript("shell", "packages/shell/src/cli.ts", 9, 3),
        typescript("core", "packages/core/src/index.ts", 1, 3),
        exceptions=entry("packages/ui/src/view.tsx", "shell"),
    )
    assert lines == (
        f"packages/shell/src/cli.ts:9: the shell function `f9` makes 3 decisions (limit 2){MOVE}",
        "Found 1 issues",
    )
    assert status == 1
    assert files == "packages/ui/src/view.tsx\npackages/shell/src/cli.ts\n"


def test_a_shell_exception_on_package_json_lifts_the_typescript_share() -> None:
    lines = tuple(
        typescript("ui", "packages/ui/src/view.tsx", line, 2)
        for line in range(10)
    )
    assert typescript_shared(*lines)[1] == 1
    assert (
        typescript_shared(*lines, exceptions=entry("Cargo.toml", "shell"))[1]
        == 1
    )
    assert typescript_shared(
        *lines, exceptions=entry("package.json", "shell")
    ) == (("shell makes 20 of 20 decisions",), 0)
