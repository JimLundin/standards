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
# The standard's config files that a project copies to its root. Oxlint's
# type-aware rules read the tsconfig.json there, which extends the
# standard's. Oxlint runs on the standard's config, as in a project without
# its own.
COPIED = FrozenList((
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


COMMIT_UNITS = FrozenList((
    "exceptions",
    "format",
    "lint",
    "types",
    "unused",
    "api",
    "shell",
    "shell-share",
))


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


# Indented by tabs; oxfmt indents by two spaces.
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


FLOATING = """import { Console } from "effect";

export const start = (): void => {
  Console.log("started");
};
"""
MISTYPED = """export const count: number = "one";
"""


@pytest.mark.parametrize(
    ("path", "text", "diagnostic"),
    [
        ("packages/shell/src/floating.ts", FLOATING, "error TS377001"),
        ("packages/core/src/mistyped.ts", MISTYPED, "error TS2322"),
    ],
    ids=["floating-effect", "plain-type-error"],
)
def test_a_floating_effect_or_a_type_error_fails_types(
    fixtures: Fixtures, path: str, text: str, diagnostic: str
) -> None:
    run = fixtures.check("commit", files={path: text})
    types = run.units["types"]
    assert types.outcome == "FAIL"
    assert f"{path}(" in types.findings
    assert diagnostic in types.findings


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


LAYERS = FrozenList(("core", "shell", "ui"))
# ADR 0004's bans, each a file with its one break and the rule that reports it.
AWAITED = """export const awaited = async (load: () => Promise<string>): Promise<string> => {
	const loaded = await load();
	return loaded;
};
"""
PROMISED = """export const promised = (value: string): Promise<string> =>
	new Promise((resolve) => {
		resolve(value);
	});
"""
CHAINED = """export const chained = (load: () => Promise<string>): Promise<string> =>
	load().then((loaded) => loaded.trim());
"""
THROWN = """export const thrown = (reason: string): never => {
	throw new Error(reason);
};
"""
TRIED = """export const tried = (run: () => string, fallback: string): string => {
	try {
		return run();
	} catch {
		return fallback;
	}
};
"""
PARSED = """export const parsed = (text: string): boolean =>
	typeof JSON.parse(text) === "string";
"""
LOGGED = """export const logged = (text: string): void => {
	console.log(text);
};
"""
BANS = FrozenOrderedDict({
    "awaited": ("oxc(no-async-await)", AWAITED),
    "promised": ("promise(avoid-new)", PROMISED),
    "chained": ("eslint(no-restricted-properties)", CHAINED),
    "thrown": ("standards(no-throw)", THROWN),
    "tried": ("standards(no-try)", TRIED),
    "parsed": ("eslint(no-restricted-properties)", PARSED),
    "dated": ("eslint(no-restricted-globals)", TIMED),
    "rolled": (
        "eslint(no-restricted-properties)",
        "export const rolled = (): number => Math.random();\n",
    ),
    "identified": (
        "eslint(no-restricted-globals)",
        "export const identified = (): string => crypto.randomUUID();\n",
    ),
    "timed": (
        "eslint(no-restricted-globals)",
        "export const timed = (): number => performance.now();\n",
    ),
    "logged": ("eslint(no-console)", LOGGED),
})
# Effect's own bridge, clock and randomness.
EFFECTFUL = """import { Clock, Effect, Random } from "effect";

const loaded = (load: () => Promise<string>): Effect.Effect<string, string> =>
	Effect.tryPromise({ catch: () => "unloaded", try: load });
const stamped: Effect.Effect<number> = Clock.currentTimeMillis;
const rolled: Effect.Effect<number> = Random.next;

export { loaded, rolled, stamped };
"""


def test_each_ban_fails_lint_in_every_layer_with_one_finding(
    fixtures: Fixtures,
) -> None:
    banned = FrozenOrderedDict(
        (f"packages/{layer}/src/{name}.ts", (rule, text))
        for layer in LAYERS
        for name, (rule, text) in BANS.items()
    )
    run = fixtures.check(
        "commit", files={path: text for path, (_, text) in banned.items()}
    )
    lint = run.units["lint"]
    assert lint.outcome == "FAIL"
    for path, (rule, _) in banned.items():
        found = FrozenList(
            line for line in lint.findings.splitlines() if f"{path}:" in line
        )
        assert len(found) == 1, (path, found)
        assert rule in lint.findings, rule


def test_effect_try_promise_clock_and_random_pass_lint(
    fixtures: Fixtures,
) -> None:
    # The core imports no Effect module, by its layer's import override.
    effectful = FrozenList(
        f"packages/{layer}/src/effectful.ts" for layer in ("shell", "ui")
    )
    run = fixtures.check("commit", files=dict.fromkeys(effectful, EFFECTFUL))
    lint = run.units["lint"]
    assert lint.outcome == "ok", lint.findings
    for path in effectful:
        assert path not in lint.findings, path


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


def importing(module: str) -> str:
    return f'import {{ greet }} from "{module}";\n\nexport const greeting = greet;\n'


CROSSINGS = FrozenOrderedDict({
    "packages/core/src/crossing.ts": "@fixture/shell",
    "packages/ui/src/crossing.ts": "@fixture/shell",
    "packages/shell/src/crossing.ts": "@fixture/ui",
})


def test_a_layer_crossing_fails_lint_naming_the_import(
    fixtures: Fixtures,
) -> None:
    run = fixtures.check(
        "commit",
        files={path: importing(module) for path, module in CROSSINGS.items()},
    )
    findings = run.units["lint"].findings
    assert run.units["lint"].outcome == "FAIL"
    assert findings.count("'@fixture/shell' import is restricted") == 2
    assert findings.count("'@fixture/ui' import is restricted") == 1
    for path in CROSSINGS:
        assert path in findings, path


EFFECT_MODULE = """import { succeed } from "effect/Effect";

export const one = succeed(1);
"""
HASHED = """import { empty } from "effect/HashMap";

export const none = empty<string, number>();
"""
REACTED = """import { version } from "react";

export const reactVersion: string = version;
"""


def test_a_core_import_beyond_its_allowlist_fails_lint_unless_excepted(
    fixtures: Fixtures,
) -> None:
    excepted = "packages/core/src/excepted.ts"
    unexcepted = "packages/core/src/unexcepted.ts"
    run = fixtures.check(
        "commit",
        files={
            "exceptions.toml": (
                "[[exception]]\n"
                f'path = "{excepted}"\n'
                'rule = "purity:react"\n'
                'reason = "a fixture"\n'
            ),
            "packages/core/src/effectful.ts": EFFECT_MODULE,
            "packages/core/src/hashed.ts": HASHED,
            excepted: REACTED,
            unexcepted: REACTED,
        },
    )
    findings = run.units["lint"].findings
    assert run.units["exceptions"].outcome == "ok", run.units["exceptions"]
    assert run.units["lint"].outcome == "FAIL"
    assert findings.count("'effect/Effect' import is restricted") == 1
    assert findings.count("'effect/HashMap' import is restricted") == 1
    assert findings.count("'react' import is restricted") == 1
    assert unexcepted in findings
    assert excepted not in findings


def component(name: str, imports: str, body: str) -> str:
    return (
        'import type { ReactElement } from "react";\n'
        f"{imports}\n"
        f"export const {name} = (): ReactElement => {body};\n"
    )


EFFECTED = """import type { ReactElement } from "react";
import { {hook} } from "react";

interface Shown {
	readonly onShow: () => void;
}

export const {name} = ({ onShow }: Shown): ReactElement => {
	{hook}(() => {
		onShow();
	}, [onShow]);
	return <p />;
};
"""
# Each break of the UI's bans, with the rule that reports it.
UI_BANS = FrozenOrderedDict({
    "packages/ui/src/effected.tsx": (
        "eslint(no-restricted-imports)",
        EFFECTED.replace("{hook}", "useEffect").replace("{name}", "Effected"),
    ),
    "packages/ui/src/laid.tsx": (
        "eslint(no-restricted-imports)",
        EFFECTED.replace("{hook}", "useLayoutEffect").replace("{name}", "Laid"),
    ),
    "packages/ui/src/windowed.tsx": (
        "eslint(no-restricted-globals)",
        component("Windowed", "", "<p>{window.name}</p>"),
    ),
    "packages/ui/src/documented.tsx": (
        "eslint(no-restricted-globals)",
        component("Documented", "", "<p>{document.title}</p>"),
    ),
    "packages/ui/src/stored.tsx": (
        "eslint(no-restricted-globals)",
        component("Stored", "", '<p>{localStorage.getItem("name")}</p>'),
    ),
    "packages/ui/src/reached.tsx": (
        "eslint(no-restricted-properties)",
        component("Reached", "", "<p>{globalThis.document.title}</p>"),
    ),
})
TOGGLED = """import { useCallback, useState } from "react";
import { AsyncResult } from "effect/reactivity";
import type { ReactElement } from "react";
import { greeting } from "./greeting.ts";
import { useAtomValue } from "@effect/atom-react";

export const Toggled = (): ReactElement => {
	const [hidden, setHidden] = useState(false);
	const hide = useCallback(() => {
		setHidden(true);
	}, []);
	return (
		<button hidden={hidden} onClick={hide} type="button">
			{AsyncResult.getOrElse(useAtomValue(greeting), () => "")}
		</button>
	);
};
"""


def test_a_component_with_an_effect_hook_or_a_browser_global_fails_lint(
    fixtures: Fixtures,
) -> None:
    toggled = "packages/ui/src/toggled.tsx"
    run = fixtures.check(
        "commit",
        files={
            toggled: TOGGLED,
            **{path: text for path, (_, text) in UI_BANS.items()},
        },
    )
    lint = run.units["lint"]
    assert lint.outcome == "FAIL"
    for path, (rule, _) in UI_BANS.items():
        found = FrozenList(
            line for line in lint.findings.splitlines() if f"{path}:" in line
        )
        assert len(found) == 1, (path, found)
        assert rule in found[0], (rule, found)
    assert toggled not in lint.findings, lint.findings


# The bans of every layer that the UI's own restricted globals and
# properties must keep.
EVERYWHERE = FrozenOrderedDict({
    "fetched.ts": (
        "eslint(no-restricted-globals)",
        'export const fetched = (): Promise<Response> => fetch("/");\n',
    ),
    "waited.ts": (
        "eslint(no-restricted-globals)",
        "export const waited: string = typeof setTimeout;\n",
    ),
    "argued.ts": (
        "eslint(no-restricted-globals)",
        "export const argued = (): string => process.title;\n",
    ),
    "reached.ts": (
        "eslint(no-restricted-properties)",
        'export const reached = (): Promise<Response> =>\n\tglobalThis.fetch("/");\n',
    ),
    "stamped.ts": (
        "eslint(no-restricted-properties)",
        "export const stamped = (): number => globalThis.Date.now();\n",
    ),
})


def test_the_bans_of_every_layer_still_fail_lint_in_the_ui(
    fixtures: Fixtures,
) -> None:
    banned = FrozenOrderedDict(
        (f"packages/{layer}/src/{name}", found)
        for layer in ("core", "ui")
        for name, found in EVERYWHERE.items()
    )
    run = fixtures.check(
        "commit", files={path: text for path, (_, text) in banned.items()}
    )
    lint = run.units["lint"]
    assert lint.outcome == "FAIL"
    for path, (rule, _) in banned.items():
        found = FrozenList(
            line for line in lint.findings.splitlines() if f"{path}:" in line
        )
        assert len(found) == 1, (path, found)
        assert rule in found[0], (rule, found)


TITLED = """export const titled = (): string =>
	`${document.title} ${window.name} ${localStorage.length}`;
"""


def test_a_core_or_shell_file_is_not_held_to_the_ui_bans(
    fixtures: Fixtures,
) -> None:
    titled = FrozenList(
        f"packages/{layer}/src/titled.ts" for layer in ("core", "shell")
    )
    hooked = "packages/shell/src/hooked.ts"
    run = fixtures.check(
        "commit",
        files={
            **dict.fromkeys(titled, TITLED),
            hooked: 'export { useEffect } from "react";\n',
        },
    )
    lint = run.units["lint"]
    assert lint.outcome == "ok", lint.findings


# An if, a run of && and a ternary: 3 decisions.
ROUTED = """export const route = (path: string, verbose: boolean): string => {
	if (path === "") {
		return "root";
	}
	return verbose && path.length > 1 ? path : "short";
};
"""
# A JSX ternary, an && render and an Option.match: 3 decisions.
BADGED = """import { Option } from "effect";
import type { ReactElement } from "react";

interface Counted {
	readonly count: number;
	readonly label: Option.Option<string>;
}

export const Badge = (props: Counted): ReactElement => (
	<p>
		{props.count > 0 ? <b>{props.count}</b> : <i>none</i>}
		{props.count > 9 && <span>many</span>}
		{Option.match(props.label, { onNone: () => "", onSome: (label) => label })}
	</p>
);
"""
THICK = FrozenOrderedDict({
    "packages/shell/src/route.ts": ROUTED,
    "packages/ui/src/badge.tsx": BADGED,
})


def shell_exceptions(*paths: str) -> str:
    return "".join(
        f'[[exception]]\npath = "{path}"\nrule = "shell"\nreason = "a fixture"\n'
        for path in paths
    )


def test_a_thick_shell_function_or_component_fails_shell_unless_excepted(
    fixtures: Fixtures,
) -> None:
    run = fixtures.check("commit", files=THICK)
    shell = run.units["shell"]
    assert shell.outcome == "FAIL"
    assert "Found 2 issues" in shell.summary
    for path in THICK:
        assert path in shell.findings, path
    assert "`route` makes 3 decisions (limit 2)" in shell.findings
    assert "`Badge` makes 3 decisions (limit 2)" in shell.findings
    excepted = fixtures.check(
        "commit", files={**THICK, "exceptions.toml": shell_exceptions(*THICK)}
    )
    assert excepted.units["exceptions"].outcome == "ok"
    assert excepted.units["shell"].outcome == "ok"


def branching(name: str, count: int) -> str:
    """`count` functions of 2 decisions each."""
    return "".join(
        f"export const {name}{index} = (value: number): number =>\n\tvalue > {index} ? (value > {index + 1} ? 1 : 2) : 3;\n"
        for index in range(count)
    )


# 6 of 20 decisions in the shell and the UI, each function within the limit.
SHARED = FrozenOrderedDict({
    "packages/core/src/branches.ts": branching("core", 7),
    "packages/shell/src/branches.ts": branching("shell", 2),
    "packages/ui/src/branches.ts": branching("ui", 1),
})


def test_a_shell_and_ui_over_a_quarter_of_the_decisions_fail_shell_share(
    fixtures: Fixtures,
) -> None:
    run = fixtures.check("commit", files=SHARED)
    assert run.units["shell"].outcome == "ok"
    share = run.units["shell-share"]
    assert share.outcome == "FAIL"
    assert "package.json: the shell makes 6 of 20 decisions" in share.findings
    excepted = fixtures.check(
        "commit",
        files={**SHARED, "exceptions.toml": shell_exceptions("package.json")},
    )
    assert excepted.units["exceptions"].outcome == "ok"
    assert excepted.units["shell-share"].outcome == "ok"
    assert (
        "shell makes 6 of 20 decisions" in excepted.units["shell-share"].summary
    )


# Each kind of export the core's API may not have, the class's through an alias.
UNDATA = FrozenOrderedDict({
    "packages/core/src/callback.ts": (
        "export const applied = (f: (n: number) => number): number => f(1);\n"
    ),
    "packages/core/src/promised.ts": (
        "export const promised = (): Promise<number> => Promise.resolve(1);\n"
    ),
    "packages/core/src/effect.ts": (
        'import { Effect } from "effect";\n\n'
        "export const one = (): Effect.Effect<number> => Effect.succeed(1);\n"
    ),
    "packages/core/src/iterated.ts": (
        "export const counted = (values: Iterable<number>): number =>\n"
        "\t[...values].length;\n"
    ),
    "packages/core/src/runner.ts": (
        "class Runner {\n"
        "\trun(): number {\n"
        "\t\treturn 1;\n"
        "\t}\n"
        "}\n\n"
        "type Ran = Runner;\n\n"
        "export const runner = (ran: Ran): Ran => ran;\n"
    ),
})


def api_exceptions(*paths: str) -> str:
    return "".join(
        f'[[exception]]\npath = "{path}"\nrule = "api"\nreason = "a fixture"\n'
        for path in paths
    )


def test_a_core_export_that_takes_more_than_data_fails_api_unless_excepted(
    fixtures: Fixtures,
) -> None:
    run = fixtures.check("commit", files=UNDATA)
    api = run.units["api"]
    assert api.outcome == "FAIL"
    assert "Found 5 issues" in api.summary
    for path in UNDATA:
        assert path in api.findings, path
    assert "`promised` reaches `Promise`" in api.findings
    assert "`one` reaches `Effect.Effect`" in api.findings
    excepted = fixtures.check(
        "commit", files={**UNDATA, "exceptions.toml": api_exceptions(*UNDATA)}
    )
    assert excepted.units["exceptions"].outcome == "ok"
    assert excepted.units["api"].outcome == "ok"
