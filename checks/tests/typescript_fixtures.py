"""typescript/check.sh on the fixture workspaces of typescript/fixtures.

The `typescript-fixtures` suite of checks.toml runs this file by name at
tier step, since its npm install needs Node and the network; a name without
the `test_` prefix keeps it out of the test unit.
"""

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
lazy from collections.abc import Mapping

import pytest
from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from tests.test_lib import STANDARDS, git

TYPESCRIPT = STANDARDS / "typescript"
FIXTURES = TYPESCRIPT / "fixtures"
COMPLIANT = "compliant"
# The standard's config files that a project copies to its root. Biome reads
# a workspace's package.json files only from a config at the project root,
# and Oxlint's type-aware rules read the tsconfig.json there, which extends
# the standard's.
COPIED = FrozenList((
    "biome.json",
    "biome-plugins",
    "knip.json",
    "oxlint.config.ts",
    "profiles",
    "tsconfig.base.json",
))
OUTCOMES = FrozenOrderedSet(("ok", "flaky", "skip", "FAIL"))
NO_FILES: FrozenOrderedDict[str, str] = FrozenOrderedDict()
LOGS = re.compile(r"^tier: \w+, logs: (.+)$")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True, slots=True)
class Verdict:
    """A unit's line of the run, and its log."""

    outcome: str
    summary: str
    findings: str


@dataclass(frozen=True, slots=True)
class Checked:
    status: int
    units: FrozenOrderedDict[str, Verdict]

    def failing(self) -> FrozenOrderedDict[str, Verdict]:
        return FrozenOrderedDict(
            (name, verdict)
            for name, verdict in self.units.items()
            if verdict.outcome not in {"ok", "flaky"}
        )


@dataclass(frozen=True, slots=True)
class Fixtures:
    """Checks a fixture tree in a throwaway git project whose origin is a
    bare repository beside it.

    A project is the compliant tree with the standard's copied config at its
    root, then the named tree, which holds only the files it changes, then
    `files`, each a path and its text. Its node_modules link to one install
    of the compliant tree, so a tree can't add a dependency.
    """

    root: Path
    installed: Path

    def check(
        self,
        tier: str,
        tree: str = COMPLIANT,
        files: Mapping[str, str] = NO_FILES,
    ) -> Checked:
        project = self.project(tree, files)
        done = subprocess.run(
            ("bash", str(TYPESCRIPT / "check.sh"), tier, str(project)),
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "STANDARDS_CACHE": str(self.root / "cache")},
        )
        return checked(done.returncode, done.stdout)

    def project(self, tree: str, files: Mapping[str, str]) -> Path:
        work = Path(tempfile.mkdtemp(prefix=f"{tree}.", dir=self.root))
        project = work / "project"
        lay(FIXTURES / COMPLIANT, project)
        for name in COPIED:
            lay(TYPESCRIPT / name, project / name)
        if tree != COMPLIANT:
            lay(FIXTURES / tree, project)
        for path, text in files.items():
            (project / path).parent.mkdir(parents=True, exist_ok=True)
            _ = (project / path).write_text(text, newline="\n")
        _ = shutil.copytree(
            self.installed / "node_modules",
            project / "node_modules",
            symlinks=True,
            copy_function=os.link,
        )
        _ = git(work, "init", "-q", "--bare", "origin.git")
        _ = git(project, "init", "-q")
        for setting in (
            ("user.name", "fixture"),
            ("user.email", "fixture@example.com"),
        ):
            _ = git(project, "config", *setting)
        _ = git(project, "remote", "add", "origin", str(work / "origin.git"))
        _ = git(project, "add", "-A")
        _ = git(project, "commit", "-q", "-m", "fixture")
        return project


def lay(source: Path, target: Path) -> None:
    if source.is_dir():
        _ = shutil.copytree(
            source,
            target,
            ignore=shutil.ignore_patterns("node_modules"),
            dirs_exist_ok=True,
        )
    else:
        _ = shutil.copyfile(source, target)


def checked(status: int, stdout: str) -> Checked:
    lines = stdout.splitlines()
    logs = next(
        (Path(found[1]) for line in lines if (found := LOGS.match(line))), None
    )
    units: dict[str, Verdict] = {}
    for line in lines:
        name, outcome, summary = (*line.split(maxsplit=2), "", "")[:3]
        if outcome not in OUTCOMES:
            continue
        log = logs / f"{name}.log" if logs else None
        findings = log.read_text() if log and log.exists() else ""
        units[name] = Verdict(outcome, summary, ANSI.sub("", findings))
    return Checked(status, FrozenOrderedDict(units))


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory: pytest.TempPathFactory) -> Fixtures:
    root = tmp_path_factory.mktemp("typescript")
    installed = root / "installed"
    lay(FIXTURES / COMPLIANT, installed)
    _ = subprocess.run(
        ("npm", "ci", "--no-audit", "--no-fund", "--loglevel=error"),
        cwd=installed,
        check=True,
    )
    return Fixtures(root, installed)


COMMIT_UNITS = FrozenList(("exceptions", "format", "lint", "types", "unused"))


@pytest.mark.parametrize(
    ("tier", "units"),
    [("commit", COMMIT_UNITS), ("step", FrozenList((*COMMIT_UNITS, "test")))],
    ids=["commit", "step"],
)
def test_the_compliant_tree_passes_every_unit(
    fixtures: Fixtures, tier: str, units: FrozenList[str]
) -> None:
    run = fixtures.check(tier)
    assert run.failing() == {}
    assert FrozenList(run.units) == units
    assert run.status == 0


def test_a_suppression_comment_fails_exceptions(fixtures: Fixtures) -> None:
    suppressed = "packages/core/src/suppressed.ts"
    run = fixtures.check(
        "commit",
        files={
            suppressed: (
                "// biome-ignore lint/style/useConst: a fixture\n"
                "export const suppressed = 1;\n"
            )
        },
    )
    assert run.units["exceptions"].outcome == "FAIL"
    assert suppressed in run.units["exceptions"].findings


DEFERRED = """export const defer = (task: () => void): void => {
	queueMicrotask(task);
};
"""
STARTED = """const work = async (): Promise<void> => {
	await Promise.resolve();
};

export const start = (): void => {
	work();
};
"""
MASKED = """export const masked = (left: number, right: number): number => left & right;
"""


def test_a_break_of_each_kind_of_rule_fails_lint_naming_the_rule(
    fixtures: Fixtures,
) -> None:
    breaks = FrozenList((
        (
            "packages/core/src/deferred.ts",
            "eslint(no-restricted-globals)",
            DEFERRED,
        ),
        (
            "packages/core/src/started.ts",
            "typescript(no-floating-promises)",
            STARTED,
        ),
        ("packages/core/src/masked.ts", "eslint(no-bitwise)", MASKED),
    ))
    run = fixtures.check(
        "commit", files={path: text for path, _, text in breaks}
    )
    findings = run.units["lint"].findings
    assert run.units["lint"].outcome == "FAIL"
    for path, rule, _ in breaks:
        assert findings.count(rule) == 1, rule
        assert path in findings, path


def test_an_exception_clears_its_rule_in_its_file_alone(
    fixtures: Fixtures,
) -> None:
    excepted = "packages/core/src/masked.ts"
    unexcepted = "packages/core/src/unmasked.ts"
    run = fixtures.check(
        "commit",
        files={
            "exceptions.toml": (
                "[[exception]]\n"
                f'path = "{excepted}"\n'
                'rule = "lint/eslint/no-bitwise"\n'
                'reason = "a fixture"\n'
            ),
            excepted: MASKED,
            unexcepted: MASKED,
        },
    )
    findings = run.units["lint"].findings
    assert run.units["exceptions"].outcome == "ok"
    assert run.units["lint"].outcome == "FAIL"
    assert findings.count("eslint(no-bitwise)") == 1
    assert unexcepted in findings
    assert excepted not in findings
