"""lib.sh in fixture workspaces: a git project whose origin is a bare
repository beside it, so recorded passes go nowhere else."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
lazy from collections.abc import Sequence

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
unit present ending bash -c 'echo ran >>"$MARKER"; [ -z "${{REWRITE:-}}" ] || echo x >>"$REWRITE"'
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
    errors: str


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
        more: Sequence[str] = (),
    ) -> Run:
        settings = (
            f"STANDARDS={STANDARDS}",
            f"STANDARDS_CACHE={self.root / 'cache'}",
            f"MARKER={self.root / 'marker'}",
            f"ROOT={self.root}",
            f"PRESENT_TOOL={present_tool}",
            *(("CI=true",) if ci else ()),
            *(("ONLY_PRESENT=1",) if only_present else ()),
            *more,
        )
        done = subprocess.run(
            (
                "env",
                "-u",
                "CI",
                "-u",
                "STANDARDS_LOCAL_TIERS",
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
        return Run(
            done.returncode, FrozenList(done.stdout.splitlines()), done.stderr
        )

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


STEP_SUITE = """\
[[suite]]
name = "step-suite"
command = "true"
[[suite.when]]
tier = "step"
"""
LOCAL_TIERS = "STANDARDS_LOCAL_TIERS=1"


@pytest.fixture
def stepped(workspace: Workspace) -> Workspace:
    _ = (workspace.project / "checks.toml").write_text(STEP_SUITE)
    return workspace


def test_with_no_tier_only_the_commit_units_run(stepped: Workspace) -> None:
    run = stepped.run(only_present=True, more=(LOCAL_TIERS,))
    assert run.status == 0
    assert outcome(run, "present") == ("ok",)
    assert outcome(run, "step-suite") == ()
    assert run.lines[-1].startswith("tier: commit,")


@pytest.mark.parametrize("tier", ["step", "release"])
def test_a_local_tier_outside_ci_stops_before_any_unit(
    stepped: Workspace, tier: str
) -> None:
    run = stepped.run(tier, only_present=True)
    assert run.status == 2
    assert run.lines == ()
    assert f"{tier} runs only in CI" in run.errors
    assert LOCAL_TIERS in run.errors
    assert stepped.runs() == 0


@pytest.mark.parametrize("allowance", [LOCAL_TIERS, "CI=true"])
def test_step_runs_where_local_tiers_are_allowed_or_in_ci(
    stepped: Workspace, allowance: str
) -> None:
    run = stepped.run("step", only_present=True, more=(allowance,))
    assert run.status == 0
    assert outcome(run, "present") == ("ok",)
    assert outcome(run, "step-suite") == ("ok",)


def test_dry_runs_of_step_need_no_allowance(stepped: Workspace) -> None:
    allowed = stepped.run("step", only_present=True, more=(LOCAL_TIERS,))
    assert allowed.status == 0
    assert stepped.run("step", "--verify", only_present=True).status == 0
    assert stepped.run("step", "--affected", only_present=True).status == 0
    assert stepped.runs() == 1


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


def test_a_pass_whose_project_changed_while_it_ran_is_not_recorded(
    workspace: Workspace,
) -> None:
    changed = f"REWRITE={workspace.project / 'rewritten.txt'}"
    run = workspace.run("commit", only_present=True, more=(changed,))
    assert outcome(run, "present") == ("ok",)
    assert not workspace.pushed()
    again = workspace.run("commit", only_present=True)
    assert outcome(again, "present") == ("ok",)
    assert workspace.runs() == 2


# A check script of one package check over a workspace of two packages,
# where app depends on core.
PACKAGES = """\
set -uo pipefail
source "$STANDARDS/lib.sh"
arguments "$@"
cd "$project" || exit 2
begin rust
cp "$ROOT/metadata.json" "$logs/metadata.json"
units --toolchain=fixture "--metadata=$(native "$logs/metadata.json")" --package=lint
lint() { echo ran >>"$MARKER"; }
batch lint ending lint "${members[@]}"
finish
"""


@pytest.fixture
def packages(workspace: Workspace) -> Workspace:
    root = workspace.project.as_posix()
    _ = (workspace.root / "driver.sh").write_text(PACKAGES, newline="\n")
    _ = (workspace.root / "metadata.json").write_text(
        json.dumps({
            "workspace_root": root,
            "packages": [
                {
                    "name": "core",
                    "manifest_path": f"{root}/crates/core/Cargo.toml",
                    "dependencies": [],
                },
                {
                    "name": "app",
                    "manifest_path": f"{root}/crates/app/Cargo.toml",
                    "dependencies": [{"path": f"{root}/crates/core"}],
                },
            ],
        })
    )
    for name in ("core", "app"):
        (workspace.project / "crates" / name).mkdir(parents=True)
        _ = (workspace.project / "crates" / name / "lib.rs").write_text("")
    return workspace


def affected(workspace: Workspace) -> FrozenList[str]:
    run = workspace.run("commit", "--affected")
    assert run.status == 0
    return run.lines


def test_affected_lists_the_changed_packages_and_their_dependents(
    packages: Workspace,
) -> None:
    assert affected(packages) == ("core", "app")
    assert packages.run("commit").status == 0
    assert affected(packages) == ()
    _ = (packages.project / "crates/core/lib.rs").write_text("changed")
    assert affected(packages) == ("core", "app")
    assert packages.run("commit").status == 0
    _ = (packages.project / "crates/app/lib.rs").write_text("changed")
    assert affected(packages) == ("app",)
    assert packages.runs() == 2


def test_affected_and_verify_are_not_run_together(workspace: Workspace) -> None:
    assert workspace.run("commit", "--affected", "--verify").status == 2


FAKE_SCCACHE = """\
#!/bin/sh
echo "$@" >>"$CALLS"
exit 2
"""


def source_build(root: Path, *settings: str) -> str:
    fake = root / "bin/sccache"
    fake.parent.mkdir()
    _ = fake.write_text(FAKE_SCCACHE, newline="\n")
    fake.chmod(0o755)
    return subprocess.run(
        (
            "env",
            "-u",
            "RUSTC_WRAPPER",
            f"BIN={root / 'bin'}",
            f"CALLS={root / 'calls'}",
            f"BUILD={STANDARDS / 'rust/build.sh'}",
            *settings,
            "bash",
            "-c",
            'PATH="$BIN:$PATH"; source "$BUILD" && echo "$RUSTC_WRAPPER"',
        ),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_setting_the_sccache_wrapper_starts_its_server(tmp_path: Path) -> None:
    assert source_build(tmp_path) == "sccache\n"
    assert (tmp_path / "calls").read_text() == "--start-server\n"


def test_a_wrapper_the_caller_set_starts_no_server(tmp_path: Path) -> None:
    assert source_build(tmp_path, "RUSTC_WRAPPER=other") == "other\n"
    assert not (tmp_path / "calls").exists()
