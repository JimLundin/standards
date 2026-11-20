import json
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict

from checks.core.rust_shell import (
    Failure,
    Function,
    measured,
    records,
    request,
    roots,
    roots_request,
    run,
    targets,
)
from checks.core.values import Inputs, Request, parse_json

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
    *lines: str, skips: Sequence[str] = ()
) -> tuple[FrozenList[str], int, str]:
    texts = FrozenOrderedDict({"m.json": METADATA, "d.jsonl": "\n".join(lines)})
    result = run((*skips, "m.json", "d.jsonl", "files.txt"), Inputs(texts))
    return result.lines, result.status, result.writes["files.txt"]


def test_requests_read_the_metadata_and_the_measures() -> None:
    assert roots_request(("m.json",), Inputs()) == Request(
        FrozenList(("m.json",))
    )
    assert request(
        ("--skip=x", "m.json", "d.jsonl", "files.txt"), Inputs()
    ) == Request(FrozenList(("m.json", "d.jsonl")))


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


def test_complex_shell_functions_can_be_excepted() -> None:
    lines, status, _ = outcome(
        shell("src/main.rs", 7, 3), skips=("--skip=src/*.rs",)
    )
    assert lines == ("shell makes 3 of 3 decisions",)
    assert status == 0


def test_unmeasured_files_fail_unless_excepted() -> None:
    broken = failure(f"{ROOT}\\src\\gen.rs", "No such file")
    lines, status, _ = outcome(broken, shell("src/main.rs", 1, 1))
    assert lines == (
        "src/gen.rs: cannot be measured: No such file",
        "Found 1 issues",
    )
    assert status == 1
    assert outcome(broken, skips=("--skip=src/gen.rs",))[:2] == (
        ("no shell",),
        0,
    )


def test_the_shell_share_applies_from_twenty_decisions() -> None:
    shell_lines = (shell("src/main.rs", line, 2) for line in range(3))
    lines, status, _ = outcome(*shell_lines, core("src/lib.rs", 1, 15))
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
        return outcome(*shell_lines, core("src/lib.rs", 1, core_decisions))[0]

    assert share(5, 15) == ("shell makes 5 of 20 decisions",)
    assert share(6, 14) == (
        f"Cargo.toml: the shell makes 6 of 20 decisions (limit 25%){MOVE}",
        "Found 1 issues",
    )
    assert share(6, 13) == ("shell makes 6 of 19 decisions",)


def test_the_shell_share_can_be_excepted() -> None:
    shell_lines = (shell("src/main.rs", line, 2) for line in range(10))
    lines, status, _ = outcome(*shell_lines, skips=("--skip=Cargo.toml",))
    assert lines == ("shell makes 20 of 20 decisions",)
    assert status == 0
