import io
import json
import runpy
import sys
lazy from pathlib import Path

import pytest
from ordered import FrozenList, FrozenOrderedDict

from checks import notes
from checks.core.tools import TOOLS, request, run
from checks.core.values import Inputs, Request
from checks.shell import gather, main, read


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def invoke(
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
    *arguments: str,
    stdin: str = "",
) -> tuple[int, str]:
    monkeypatch.setattr(sys, "argv", ["checks", *arguments])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    status = main()
    return status, capsysbinary.readouterr().out.decode()


def test_tools_dispatch_to_each_tool() -> None:
    assert tuple(TOOLS) == (
        "core-clippy",
        "core-libraries",
        "immutability",
        "passed",
        "policy",
        "purity",
        "rust-api",
        "rust-core",
        "rust-roots",
        "rust-shell",
        "rust-shell-share",
        "slop",
        "structure",
        "units",
        "ruff-config",
        "without",
        "globs",
        "biome-groups",
        "biome-plugins",
        "filter-mutmut",
        "stryker-mutate",
        "nextest-config",
    )
    assert request(("immutability", "a.py"), Inputs()) == Request(
        FrozenList(("exceptions.toml", "a.py"))
    )
    texts = FrozenOrderedDict({"a.py": "x = 1\n"})
    assert tuple(run(("immutability", "a.py"), Inputs(texts)).lines) == (
        "All checks passed",
    )


def test_read_skips_missing_paths_and_directories(project: Path) -> None:
    _ = (project / "a.txt").write_text("é\n", encoding="utf-8")
    (project / "folder").mkdir()
    assert read(FrozenList(("a.txt", "missing.txt", "folder"))) == {
        "a.txt": "é\n"
    }


def test_gather_reads_in_rounds_and_only_once(project: Path) -> None:
    _ = (project / "m.json").write_text(
        json.dumps({
            "target_directory": project.as_posix(),
            "packages": [
                {"name": "c", "targets": [{"name": "c", "kind": ["lib"]}]}
            ],
        }),
        encoding="utf-8",
    )
    (project / "doc").mkdir()
    _ = (project / "doc" / "c.json").write_text("{}", encoding="utf-8")
    inputs = gather(FrozenList(("rust-api", "m.json", "c")))
    assert tuple(inputs.texts) == ("m.json", f"{project.as_posix()}/doc/c.json")
    assert not inputs.stdin
    assert inputs.cwd == str(project)


def test_main_prints_lines_and_returns_the_status(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    _ = (project / "a.py").write_text("x = {1}\n", encoding="utf-8")
    status, out = invoke(monkeypatch, capsysbinary, "immutability", "a.py")
    assert status == 1
    assert out == (
        "a.py:1:5: IMM004 a set literal iterates in hash order, which changes "
        "per process; use FrozenOrderedSet\nFound 1 issues\n"
    )


def test_main_runs_the_notes_in_the_working_directory(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    key = "1" * 40
    assert notes.git(str(project), "init", "-q").returncode == 0
    status, out = invoke(
        monkeypatch, capsysbinary, "notes", "record", key, "python lint ."
    )
    assert (status, out) == (0, f"{key}\n")
    status, out = invoke(monkeypatch, capsysbinary, "notes", "lookup")
    assert (status, out) == (0, f"{key}\n")


def test_main_reads_stdin_only_when_asked(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    _ = (project / "exceptions.toml").write_text(
        '[[exception]]\npath = "app/x.py"\nrule = "mutation"\nreason = "r"\n',
        encoding="utf-8",
    )
    lines = "app.x.f__mutmut_1: survived\napp.y.g__mutmut_2: survived\n"
    status, out = invoke(
        monkeypatch, capsysbinary, "filter-mutmut", stdin=lines
    )
    assert (status, out) == (0, "app.y.g__mutmut_2: survived\n")
    status, out = invoke(
        monkeypatch, capsysbinary, "globs", "mutation", stdin=lines
    )
    assert (status, out) == (0, "app/x.py\n")


def test_main_writes_what_the_core_returns(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    root = project.as_posix()
    _ = (project / "m.json").write_text(
        json.dumps({
            "workspace_root": root,
            "packages": [
                {
                    "targets": [
                        {"kind": ["bin"], "src_path": f"{root}/src/main.rs"}
                    ]
                }
            ],
        }),
        encoding="utf-8",
    )
    record = {
        "root": f"{root}/src/main.rs",
        "path": f"{root}/src/main.rs",
        "function": "main",
        "line": 1,
        "decisions": 1,
    }
    _ = (project / "d.jsonl").write_text(json.dumps(record), encoding="utf-8")
    status, out = invoke(
        monkeypatch,
        capsysbinary,
        "rust-shell",
        "m.json",
        "d.jsonl",
        "files.txt",
    )
    assert (status, out) == (0, "shell makes 1 of 1 decisions\n")
    assert (project / "files.txt").read_text(
        encoding="utf-8"
    ) == "src/main.rs\n"


def test_main_writes_utf8(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    _ = (project / "é.py").write_text("x = {1}\n", encoding="utf-8")
    _, out = invoke(monkeypatch, capsysbinary, "immutability", "é.py")
    assert out.startswith("é.py:1:5: IMM004")


def test_module_exits_with_the_status(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    _ = (project / "a.py").write_text("x = {1}\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["checks", "immutability", "a.py"])
    with pytest.raises(SystemExit) as exit_info:
        _ = runpy.run_module("checks", run_name="__main__")
    assert exit_info.value.code == 1
    assert capsysbinary.readouterr().out.endswith(b"Found 1 issues\n")


def test_read_normalizes_windows_line_endings(project: Path) -> None:
    _ = (project / "a.txt").write_bytes(b"one\r\ntwo\n")
    assert read(FrozenList(("a.txt",))) == {"a.txt": "one\ntwo\n"}


def test_main_resolves_paths_against_the_working_directory(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    (project / "conf").mkdir()
    _ = (project / "conf" / "biome.json").write_text(
        '{"plugins": ["p/a.grit"]}', encoding="utf-8"
    )
    status, out = invoke(
        monkeypatch, capsysbinary, "biome-plugins", "conf/biome.json"
    )
    assert (status, out) == (0, f"a|{project.as_posix()}/conf/p/a.grit\n")
