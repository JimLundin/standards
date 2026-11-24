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
# the standard's. Oxlint runs on the standard's config, as in a project
# without its own.
COPIED = FrozenList((
    "biome.json",
    "knip.json",
    "stryker.config.json",
    "tsconfig.base.json",
    "vitest.config.ts",
    "vitest.setup.ts",
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


# Indented by tabs, as Biome formats it; oxfmt indents by two spaces.
TABBED = """export const double = (value: number): number => {
\treturn value * 2;
};
"""


def unsorted_package() -> str:
    """The compliant core package.json, with `name` moved below `private`."""
    path = FIXTURES / COMPLIANT / "packages/core/package.json"
    lines = path.read_text().splitlines(keepends=True)
    named = next(index for index, line in enumerate(lines) if '"name"' in line)
    private = lines.pop(named + 1)
    assert '"private"' in private
    lines.insert(named, private)
    return "".join(lines)


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("packages/core/src/tabbed.ts", TABBED),
        ("packages/core/package.json", unsorted_package()),
    ],
    ids=["misformatted-ts", "unsorted-package-json"],
)
def test_a_misformatted_file_fails_format_naming_it(
    fixtures: Fixtures, path: str, text: str
) -> None:
    run = fixtures.check("commit", files={path: text})
    format_ = run.units["format"]
    assert format_.outcome == "FAIL"
    assert path in format_.findings


@pytest.mark.parametrize(
    "comment",
    ["// oxlint-disable-next-line no-magic-numbers", "/* eslint-disable */"],
    ids=["oxlint-disable-next-line", "eslint-disable"],
)
def test_a_lint_disable_comment_fails_exceptions(
    fixtures: Fixtures, comment: str
) -> None:
    suppressed = "packages/core/src/suppressed.ts"
    run = fixtures.check(
        "commit",
        files={suppressed: f"{comment}\nexport const suppressed = 1;\n"},
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


STATEFUL = """let count = 0;

export const bump = (): number => {
	count += 1;
	return count;
};
"""
TIMED = """export const now = (): number => Date.now();
"""
COUNTED = """export class Counter {
	count = 0;
}
"""
LISTED = """export const first = (names: string[]): string | undefined => names[0];
"""


def test_a_break_of_each_standards_rule_fails_lint_naming_the_rule(
    fixtures: Fixtures,
) -> None:
    breaks = FrozenList((
        (
            "packages/core/src/stateful.ts",
            "standards(no-module-state)",
            STATEFUL,
        ),
        (
            "packages/core/src/counted.ts",
            "standards(readonly-members)",
            COUNTED,
        ),
        ("packages/core/src/listed.ts", "standards(readonly-types)", LISTED),
        ("packages/core/src/timed.ts", "eslint(no-restricted-globals)", TIMED),
    ))
    run = fixtures.check(
        "commit", files={path: text for path, _, text in breaks}
    )
    findings = run.units["lint"].findings
    assert run.units["lint"].outcome == "FAIL"
    for path, rule, _ in breaks:
        assert findings.count(rule) == 1, rule
        assert path in findings, path


PLAIN_CLASS = """export class Greeter {}
"""
# Max-classes-per-file holds each to its own file.
EFFECT_CLASSES = FrozenOrderedDict({
    "packages/shell/src/person.ts": (
        'import { Schema } from "effect";\n\n'
        'export class Person extends Schema.Class<Person>("Person")({\n'
        "\tname: Schema.String,\n"
        "}) {}\n"
    ),
    "packages/shell/src/missing.ts": (
        'import { Data } from "effect";\n\n'
        'export class Missing extends Data.TaggedError("Missing")<{\n'
        "\treadonly path: string;\n"
        "}> {}\n"
    ),
    "packages/shell/src/clock.ts": (
        'import { Context } from "effect";\n\n'
        "export class Clock extends Context.Service<\n"
        "\tClock,\n"
        "\t{ readonly now: number }\n"
        '>()("Clock") {}\n'
    ),
})


def test_a_plain_class_fails_lint_and_an_effect_class_passes(
    fixtures: Fixtures,
) -> None:
    plain = "packages/shell/src/greeter.ts"
    run = fixtures.check("commit", files={plain: PLAIN_CLASS, **EFFECT_CLASSES})
    findings = run.units["lint"].findings
    assert run.units["lint"].outcome == "FAIL"
    assert findings.count("standards(no-plain-class)") == 1
    assert plain in findings
    for path in EFFECT_CLASSES:
        assert path not in findings, findings


HOOKED = """import type { ReactElement } from "react";
import { useState } from "react";

interface Shown {
	readonly shown: boolean;
}

export const Hooked = (props: Shown): ReactElement | undefined => {
	if (props.shown) {
		const [label] = useState("shown");
		return <p>{label}</p>;
	}
	return undefined;
};
"""
PICTURED = """import type { ReactElement } from "react";

const source = "ada.png";

export const Pictured = (): ReactElement => <img src={source} />;
"""
INDEXED = """import type { ReactElement } from "react";

interface Names {
	readonly names: ReadonlyArray<string>;
}

export const Indexed = (props: Names): ReactElement => (
	<ul>
		{props.names.map((name, index) => (
			<li key={index}>{name}</li>
		))}
	</ul>
);
"""
PRESSED = """import type { ReactElement } from "react";

interface Presses {
	readonly onPress: () => void;
}

export const Pressed = (props: Presses): ReactElement => {
	const press = (): void => {
		props.onPress();
	};
	return <button onClick={press} type="button" />;
};
"""


def test_a_break_of_each_react_and_jsx_plugin_fails_lint_naming_the_rule(
    fixtures: Fixtures,
) -> None:
    # Rules-of-hooks prints under react-hooks, though configured under react.
    # No-array-index-key is a perf rule of react that cloudflare doesn't enable.
    breaks = FrozenList((
        ("packages/core/src/hooked.tsx", "react-hooks(rules-of-hooks)", HOOKED),
        ("packages/core/src/pictured.tsx", "jsx-a11y(alt-text)", PICTURED),
        ("packages/core/src/indexed.tsx", "react(no-array-index-key)", INDEXED),
        (
            "packages/core/src/pressed.tsx",
            "react-perf(jsx-no-new-function-as-prop)",
            PRESSED,
        ),
    ))
    run = fixtures.check(
        "commit", files={path: text for path, _, text in breaks}
    )
    findings = run.units["lint"].findings
    assert run.units["lint"].outcome == "FAIL"
    for path, rule, _ in breaks:
        assert findings.count(rule) == 1, rule
        assert path in findings, path


# Typescript/promise-function-async makes a function returning a promise
# async, and typescript/require-await accepts an async function that returns
# a promise without awaiting it. Eslint's require-await, which doesn't, is off.
RETURNED = """export const returned = async (
	load: () => Promise<number>,
): Promise<number> => load();
"""


def test_an_async_function_returning_a_promise_unawaited_passes_lint(
    fixtures: Fixtures,
) -> None:
    returned = "packages/core/src/returned.ts"
    run = fixtures.check("commit", files={returned: RETURNED})
    lint = run.units["lint"]
    assert lint.outcome == "ok", lint.findings
    assert returned not in lint.findings


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


# A property test's runs in the mode the run is in: Arbitrary takes them
# from vitest.config.ts through vitest.setup.ts.
RUNS = """import { expect, it } from "@effect/vitest";
import { Arbitrary, Effect, Schema } from "effect";

const runs = Effect.map(
	Arbitrary.checkEffect(Arbitrary.schema(Schema.Number), () => true),
	(result) => (result._tag === "Passed" ? result.runs : 0),
);

it.effect("checks {fast} cases", () =>
	Effect.map(runs, (count) => {
		expect(count).toBe({fast});
	}),
);

it.effect(
	"checks {slow} cases when slow",
	() =>
		Effect.map(runs, (count) => {
			expect(count).toBe({slow});
		}),
	{ tags: ["slow"] },
);
"""


def test_step_runs_the_tests_fast_and_skips_the_slow_ones(
    fixtures: Fixtures,
) -> None:
    run = fixtures.check(
        "step",
        files={
            "packages/core/src/runs.test.ts": RUNS.replace(
                "{fast}", "10"
            ).replace("{slow}", "1000")
        },
    )
    test = run.units["test"]
    assert test.outcome == "ok", test.findings
    assert "checks 10 cases" in test.findings
    assert "1 skipped" in test.summary
    assert "Coverage report" not in test.findings


def test_release_runs_the_tests_in_full_with_coverage_and_mutation(
    fixtures: Fixtures,
) -> None:
    run = fixtures.check(
        "release",
        files={
            "packages/core/src/runs.test.ts": RUNS.replace(
                "{fast}", "1000"
            ).replace("{slow}", "1000")
        },
    )
    test = run.units["test-release"]
    assert test.outcome == "ok", test.findings
    assert "checks 1000 cases when slow" in test.findings
    assert "skipped" not in test.summary
    assert "Coverage report from v8" in test.findings
    mutation = run.units["mutation"]
    assert mutation.outcome == "ok", mutation.findings
    assert "vitest test runner" in mutation.findings


TESTED = """import { greet } from "./index.ts";
import { expect, {name} } from "{module}";

{name}("greets", () => {
	expect(greet({ name: "Ada" })).toBe("Hello, Ada");
});
"""


@pytest.mark.parametrize(
    ("name", "module", "rule"),
    [
        ("test", "@effect/vitest", "vitest(consistent-test-it)"),
        ("it", "node:test", "vitest(no-import-node-test)"),
    ],
    ids=["test", "node:test"],
)
def test_a_test_not_on_it_of_effect_vitest_fails_lint(
    fixtures: Fixtures, name: str, module: str, rule: str
) -> None:
    tested = "packages/core/src/tested.test.ts"
    run = fixtures.check(
        "commit",
        files={
            tested: TESTED.replace("{name}", name).replace("{module}", module)
        },
    )
    lint = run.units["lint"]
    assert lint.outcome == "FAIL"
    assert rule in lint.findings
    assert tested in lint.findings


def test_a_vitest_config_with_fewer_runs_drifts(fixtures: Fixtures) -> None:
    standard = (TYPESCRIPT / "vitest.config.ts").read_text()
    lowered = re.sub(r"(fast: \{[^}]*runs: )10", r"\g<1>5", standard)
    assert lowered != standard
    run = fixtures.check("commit", files={"vitest.config.ts": lowered})
    exceptions = run.units["exceptions"]
    assert exceptions.outcome == "FAIL"
    assert "drift:arbitrary.fast" in exceptions.findings


# A project's own oxlint.config.ts, which extends the standard's.
EXTENDING = """import standard from "#standards/oxlint";

const config = {
	extends: [standard],
	rules: {rules},
} as const;

export default config;
"""


@pytest.mark.parametrize(
    ("config", "rule"),
    [
        (
            EXTENDING.replace("{rules}", '{ "no-bitwise": "off" }'),
            "drift:rules.eslint/no-bitwise",
        ),
        (
            'export default { rules: { "no-bitwise": "error" } };\n',
            "drift:extends",
        ),
    ],
    ids=["rule-off", "not-extending"],
)
def test_a_weaker_oxlint_config_drifts(
    fixtures: Fixtures, config: str, rule: str
) -> None:
    run = fixtures.check("commit", files={"oxlint.config.ts": config})
    exceptions = run.units["exceptions"]
    assert exceptions.outcome == "FAIL"
    assert rule in exceptions.findings


def test_an_oxlint_config_turning_an_extra_rule_on_passes(
    fixtures: Fixtures,
) -> None:
    extra = EXTENDING.replace("{rules}", '{ "no-unreachable-loop": "error" }')
    run = fixtures.check("commit", files={"oxlint.config.ts": extra})
    exceptions = run.units["exceptions"]
    assert exceptions.outcome == "ok", exceptions.findings
    assert run.units["lint"].outcome == "ok", run.units["lint"].findings


def test_an_exception_named_as_oxlint_prints_the_rule_clears_it(
    fixtures: Fixtures,
) -> None:
    hooked = "packages/core/src/hooked.tsx"
    run = fixtures.check(
        "commit",
        files={
            "exceptions.toml": (
                "[[exception]]\n"
                f'path = "{hooked}"\n'
                'rule = "lint/react-hooks/rules-of-hooks"\n'
                'reason = "a fixture"\n'
            ),
            hooked: HOOKED,
        },
    )
    # The break also breaks react's own hooks rules, which stay.
    assert run.units["exceptions"].outcome == "ok"
    assert hooked in run.units["lint"].findings
    assert "react-hooks(rules-of-hooks)" not in run.units["lint"].findings


NODE_IMPORTS = FrozenOrderedDict({
    "packages/core/src/read.ts": (
        'import { readFileSync } from "node:fs";\n\n'
        "export const read = (path: string): string =>"
        ' readFileSync(path, "utf8");\n'
    ),
    "paths.config.ts": (
        'import { join } from "node:path";\n\n'
        'export default join("packages", "core");\n'
    ),
    "packages/core/src/tested.test.ts": TESTED.replace("{name}", "it").replace(
        "{module}", "node:test"
    ),
})


def test_a_node_import_fails_lint_in_source_config_and_test_files(
    fixtures: Fixtures,
) -> None:
    run = fixtures.check("commit", files=NODE_IMPORTS)
    findings = run.units["lint"].findings
    assert run.units["lint"].outcome == "FAIL"
    assert findings.count("import(no-nodejs-modules)") == len(NODE_IMPORTS)
    for path in NODE_IMPORTS:
        assert path in findings, path
