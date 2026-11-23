"""lib.sh in fixture workspaces: a git project whose origin is a bare
repository beside it, so recorded passes go nowhere else."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from ordered import FrozenList

from checks.core.units import pins_of

STANDARDS = Path(__file__).resolve().parents[2]
MISSING = "no-such-tool-of-the-standards"
# A check script of two project units: one that runs and appends to the
# marker, and one whose tool isn't installed; and the project's suites.
DRIVER = f"""\
set -uo pipefail
PATH="$ROOT/bin:$PATH"
source "$STANDARDS/lib.sh"
arguments "$@"
cd "$project" || exit 2
begin python
units --toolchain=fixture --project=present,absent
tools_of[present]=$PRESENT_TOOL
unit present ending bash -c 'echo ran >>"$MARKER"'
if [ -z "${{ONLY_PRESENT:-}}" ]; then
	unit absent ending {MISSING}
fi
finish
"""
SUITES = f"""\
[[suite]]
name = "absent-suite"
command = "{MISSING} --check"
[[suite.when]]
tier = "commit"
"""


@dataclass(frozen=True, slots=True)
class Run:
    status: int
    lines: FrozenList[str]


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path
    project: Path

    def run(
        self,
        *arguments: str,
        ci: bool = False,
        only_present: bool = False,
        present_tool: str = "bash",
    ) -> Run:
        settings = (
            f"STANDARDS={STANDARDS}",
            f"STANDARDS_CACHE={self.root / 'cache'}",
            f"MARKER={self.root / 'marker'}",
            f"ROOT={self.root}",
            f"PRESENT_TOOL={present_tool}",
            *(("CI=true",) if ci else ()),
            *(("ONLY_PRESENT=1",) if only_present else ()),
        )
        done = subprocess.run(
            (
                "env",
                "-u",
                "CI",
                *settings,
                "bash",
                str(self.root / "driver.sh"),
                *arguments,
                str(self.project),
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        return Run(done.returncode, FrozenList(done.stdout.splitlines()))

    def runs(self) -> int:
        marker = self.root / "marker"
        return len(marker.read_text().splitlines()) if marker.exists() else 0

    def pushed(self) -> str:
        return git(self.root / "origin.git", "notes", "--ref=checks", "list")


def git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(directory), *arguments),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def outcome(run: Run, unit: str) -> FrozenList[str]:
    return FrozenList(
        " ".join(line.split()[1:])
        for line in run.lines
        if line.split()[:1] == [unit]
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    project = tmp_path / "project"
    project.mkdir()
    _ = (tmp_path / "driver.sh").write_text(DRIVER)
    _ = git(tmp_path, "init", "-q", "--bare", "origin.git")
    _ = git(project, "init", "-q")
    for setting in (
        ("user.name", "fixture"),
        ("user.email", "fixture@example.com"),
    ):
        _ = git(project, "config", *setting)
    _ = git(project, "remote", "add", "origin", str(tmp_path / "origin.git"))
    _ = (project / "checks.toml").write_text(SUITES)
    _ = git(project, "add", "-A")
    _ = git(project, "commit", "-q", "-m", "fixture")
    return Workspace(tmp_path, project)


def test_a_unit_whose_tool_is_missing_is_skipped_outside_ci(
    workspace: Workspace,
) -> None:
    run = workspace.run("commit")
    assert run.status == 0
    assert outcome(run, "absent") == (f"skip {MISSING} not installed",)
    assert outcome(run, "absent-suite") == (f"skip {MISSING} not installed",)


def test_in_ci_a_unit_whose_tool_is_missing_fails(workspace: Workspace) -> None:
    run = workspace.run("commit", ci=True)
    assert run.status == 1
    failure = f"FAIL {MISSING} not installed; CI runs every unit"
    assert outcome(run, "absent") == (failure,)
    assert outcome(run, "absent-suite") == (failure,)
    assert outcome(run, "present") == ("ok",)


def test_a_pass_is_recorded_and_pushed_to_origin(workspace: Workspace) -> None:
    assert workspace.run("commit", only_present=True).status == 0
    again = workspace.run("commit", only_present=True)
    assert outcome(again, "present") == ("ok passed (recorded)",)
    assert workspace.runs() == 1
    assert len(workspace.pushed().splitlines()) == 1


def test_verify_refuses_a_unit_without_a_recorded_pass_and_runs_nothing(
    workspace: Workspace,
) -> None:
    _ = workspace.run("commit")
    run = workspace.run("commit", "--verify")
    assert run.status == 1
    assert outcome(run, "present") == ("ok passed (recorded)",)
    (absent,) = outcome(run, "absent")
    assert absent.startswith("FAIL no recorded pass of . under ")
    assert len(absent.split()[-1]) == 40
    (suite,) = outcome(run, "absent-suite")
    assert suite.startswith("FAIL no recorded pass of absent-suite under ")
    assert workspace.runs() == 1


def test_verify_passes_a_tree_whose_every_unit_passed(
    workspace: Workspace,
) -> None:
    _ = (workspace.project / "checks.toml").unlink()
    assert workspace.run("commit", "--verify", only_present=True).status == 1
    assert workspace.runs() == 0
    assert workspace.run("commit", only_present=True).status == 0
    assert workspace.run("commit", "--verify", only_present=True).status == 0
    assert workspace.runs() == 1


def test_verify_needs_the_recorded_passes(workspace: Workspace) -> None:
    run = workspace.run("commit", "--verify", "--no-cache")
    assert run.status == 2
    assert workspace.runs() == 0


def test_a_unit_needs_its_declared_tool_only_to_run(
    workspace: Workspace,
) -> None:
    _ = (workspace.project / "checks.toml").unlink()
    missing = workspace.run(
        "commit", ci=True, only_present=True, present_tool=MISSING
    )
    assert missing.status == 1
    assert outcome(missing, "present") == (
        f"FAIL {MISSING} not installed; CI runs every unit",
    )
    assert workspace.run("commit", only_present=True).status == 0
    recorded = workspace.run(
        "commit", ci=True, only_present=True, present_tool=MISSING
    )
    assert recorded.status == 0
    assert outcome(recorded, "present") == ("ok passed (recorded)",)


PYTHON_SUITE = """\
[[suite]]
name = "python"
command = "python3 -V"
tools = ["PYTHON"]
[[suite.when]]
tier = "commit"
"""


def test_a_suite_runs_the_pinned_python(workspace: Workspace) -> None:
    pins = pins_of((STANDARDS / "tools.env").read_text(encoding="utf-8"))
    other = workspace.root / "bin/python3"
    other.parent.mkdir()
    _ = other.write_text("#!/bin/sh\necho Python 3.0.1\n")
    other.chmod(0o755)
    _ = (workspace.project / "checks.toml").write_text(PYTHON_SUITE)
    run = workspace.run("commit", only_present=True)
    assert outcome(run, "python") == (f"ok Python {pins['PYTHON']}",)
