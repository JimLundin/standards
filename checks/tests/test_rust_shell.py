import json
lazy from collections.abc import Sequence

from ordered import FrozenList, FrozenOrderedDict

from checks.core.rust_shell import Function, function, functions, request, run
from checks.core.values import Inputs, Request, parse_json

MOVE = "; move the decisions into the core"
CORE = "path+file:///C:/work/core#0.1.0"
SHELL = "path+file:///C:/work/io#0.1.0"


def message(
    path: str,
    line: int,
    score: int,
    kind: str = "bin",
    code: str = "clippy::cognitive_complexity",
) -> str:
    return json.dumps({
        "reason": "compiler-message",
        "package_id": CORE,
        "target": {"kind": [kind]},
        "message": {
            "code": {"code": code},
            "message": f"the function has a cognitive complexity of ({score}/0)",
            "spans": [
                {
                    "file_name": "other.rs",
                    "line_start": 99,
                    "is_primary": False,
                },
                {"file_name": path, "line_start": line, "is_primary": True},
            ],
        },
    })


def in_package(record: str, package: str) -> str:
    return json.dumps({**parse_json(record), "package_id": package})


def outcome(
    *records: str, skips: Sequence[str] = (), shells: Sequence[str] = ()
) -> tuple[FrozenList[str], int, str]:
    texts = FrozenOrderedDict({"c.jsonl": "\n".join(records)})
    packages = (f"--package={shell}" for shell in shells)
    result = run((*skips, *packages, "c.jsonl", "files.txt"), Inputs(texts))
    return result.lines, result.status, result.writes["files.txt"]


def test_request_reads_the_messages() -> None:
    assert request(("--skip=x", "c.jsonl", "files.txt"), Inputs()) == Request(
        FrozenList(("c.jsonl",))
    )


def test_function_reads_cognitive_complexity_messages() -> None:
    assert function(message("src/main.rs", 3, 4), ()) == Function(
        "src/main.rs", 3, 4, in_shell=True
    )
    assert function(message("src/lib.rs", 5, 2, kind="lib"), ()) == Function(
        "src/lib.rs", 5, 2, in_shell=False
    )
    assert function(message("a.rs", 1, 1, code="clippy::other"), ()) is None
    assert (
        function(
            json.dumps({
                "reason": "compiler-message",
                "message": {"code": None},
            }),
            (),
        )
        is None
    )
    no_score = json.dumps({
        "message": {
            "code": {"code": "clippy::cognitive_complexity"},
            "message": "x",
            "spans": [],
        }
    })
    assert function(no_score, ()) is None
    no_span = json.dumps({
        "target": {"kind": ["bin"]},
        "message": {
            "code": {"code": "clippy::cognitive_complexity"},
            "message": "the function has a cognitive complexity of (2/0)",
            "spans": [
                {"file_name": "a.rs", "line_start": 1, "is_primary": False}
            ],
        },
    })
    assert function(no_span, ()) is None


def test_functions_skip_other_lines_and_duplicates() -> None:
    lines = (
        "Checking demo",
        message("src/main.rs", 1, 2),
        message("src/main.rs", 1, 2),
        message("src/lib.rs", 1, 3, kind="lib"),
    )
    assert functions(lines, ()) == (
        Function("src/main.rs", 1, 2, in_shell=True),
        Function("src/lib.rs", 1, 3, in_shell=False),
    )


def test_declared_shell_libraries_are_shell() -> None:
    shell_lib = in_package(message("io/src/lib.rs", 2, 3, kind="lib"), SHELL)
    core_lib = message("src/lib.rs", 2, 3, kind="lib")
    assert function(shell_lib, (SHELL,)) == Function(
        "io/src/lib.rs", 2, 3, in_shell=True
    )
    assert function(core_lib, (SHELL,)) == Function(
        "src/lib.rs", 2, 3, in_shell=False
    )
    assert function(shell_lib, ()) == Function(
        "io/src/lib.rs", 2, 3, in_shell=False
    )


def test_a_thin_shell_passes() -> None:
    lines, status, files = outcome(
        message("src/main.rs", 1, 3),
        message("src/io.rs", 1, 1),
        message("src/lib.rs", 1, 9, kind="lib"),
        message("src/shared.rs", 1, 1, kind="lib"),
        message("src/shared.rs", 5, 1),
    )
    assert lines == ("shell makes 2 of 10 decisions",)
    assert status == 0
    assert files == "src/main.rs\nsrc/io.rs\n"


def test_shell_files_include_shell_libraries() -> None:
    lines, status, files = outcome(
        in_package(message("io/src/lib.rs", 1, 2, kind="lib"), SHELL),
        in_package(message("io/src/main.rs", 1, 2), SHELL),
        in_package(message("io/src/both.rs", 1, 1, kind="lib"), SHELL),
        in_package(message("io/src/both.rs", 1, 1), SHELL),
        message("src/shared.rs", 1, 1, kind="lib"),
        in_package(message("src/shared.rs", 1, 1, kind="lib"), SHELL),
        message("src/lib.rs", 1, 9, kind="lib"),
        shells=(SHELL,),
    )
    assert lines == ("shell makes 2 of 10 decisions",)
    assert status == 0
    assert files == "io/src/lib.rs\nio/src/main.rs\nio/src/both.rs\n"


def test_complex_shell_library_functions_fail() -> None:
    lines, status, _ = outcome(
        in_package(message("io/src/lib.rs", 4, 4, kind="lib"), SHELL),
        message("src/lib.rs", 4, 4, kind="lib"),
        shells=(SHELL,),
    )
    assert lines == (
        f"io/src/lib.rs:4: a shell function has cognitive complexity 4 (limit 3){MOVE}",
        "Found 1 issues",
    )
    assert status == 1


def test_no_shell() -> None:
    assert outcome(message("src/lib.rs", 1, 3, kind="lib")) == (
        ("no shell",),
        0,
        "",
    )
    assert outcome() == (("no shell",), 0, "")


def test_complex_shell_functions_fail() -> None:
    lines, status, _ = outcome(
        message("src/main.rs", 7, 4), message("src/main.rs", 9, 3)
    )
    assert lines == (
        f"src/main.rs:7: a shell function has cognitive complexity 4 (limit 3){MOVE}",
        "Found 1 issues",
    )
    assert status == 1


def test_complex_shell_functions_can_be_waived() -> None:
    lines, status, _ = outcome(
        message("src/main.rs", 7, 4), skips=("--skip=src/*.rs",)
    )
    assert lines == ("shell makes 3 of 3 decisions",)
    assert status == 0


def test_the_shell_share_applies_from_twenty_decisions() -> None:
    shell = (message("src/main.rs", line, 3) for line in range(3))
    core = message("src/lib.rs", 1, 16, kind="lib")
    lines, status, _ = outcome(*shell, core)
    assert lines == (
        f"Cargo.toml: the shell makes 6 of 21 decisions (limit 25%){MOVE}",
        "Found 1 issues",
    )
    assert status == 1


def test_the_shell_share_boundaries() -> None:
    def share(functions: int, core_score: int) -> FrozenList[str]:
        shell = tuple(
            message("src/main.rs", line, 2) for line in range(functions)
        )
        return outcome(
            *shell, message("src/lib.rs", 1, core_score, kind="lib")
        )[0]

    assert share(5, 16) == ("shell makes 5 of 20 decisions",)
    assert share(6, 15) == (
        f"Cargo.toml: the shell makes 6 of 20 decisions (limit 25%){MOVE}",
        "Found 1 issues",
    )
    assert share(6, 14) == ("shell makes 6 of 19 decisions",)


def test_the_shell_share_can_be_waived() -> None:
    shell = (message("src/main.rs", line, 3) for line in range(10))
    lines, status, _ = outcome(*shell, skips=("--skip=Cargo.toml",))
    assert lines == ("shell makes 20 of 20 decisions",)
    assert status == 0
