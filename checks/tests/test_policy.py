import json

from ordered import FrozenList, FrozenOrderedDict

from checks.core.policy import request, run
from checks.core.values import Inputs, Outcome, Request
from tests.helpers import assert_lines_name_the_fix, entry, inputs, lines

STD = "C:/standards"
NEEDS = (
    "needs a path, a rule and a reason; fix: give it a non-empty `path`,"
    " `rule` and `reason`"
)
UNTRACKED = (
    "path matches no tracked file; fix: point the path at a tracked file,"
    " or remove the entry"
)
UNKNOWN = "unknown rule for rust; fix: name a rule the rust checks print, or remove the entry"


def test_request_lists_project_then_standard_files() -> None:
    files = ("src/a.py", "README.md", "tests/conftest.py")
    assert request(("python", STD, *files), Inputs()) == Request(
        FrozenList((
            "exceptions.toml",
            "pyproject.toml",
            "src/a.py",
            "tests/conftest.py",
            f"{STD}/python/pyproject.toml",
            f"{STD}/python/conftest.py",
        ))
    )


def test_policy_passes_a_clean_project() -> None:
    outcome = run(("python", STD, "a.py"), inputs({"a.py": "x = 1\n"}))
    assert outcome == Outcome(FrozenList(("All checks passed",)), 0)


def test_policy_reports_problems_exceptions_suppressions_and_drift_in_order() -> (
    None
):
    texts = {
        "exceptions.toml": entry("src/**", "E501")
        + entry("gone/**", "F401")
        + entry("src/a.py", "PUR001:x")
        + entry("pyproject.toml", "drift:tool.pytest.addopts:--b")
        + "[[exception]]\npath = 'x'\n",
        "pyproject.toml": "",
        "src/a.py": "x = 1  # noqa\n",
        f"{STD}/python/pyproject.toml": '[tool.pytest]\naddopts = ["--a", "--b"]\n',
    }
    outcome = run(("python", STD, "src/a.py", "pyproject.toml"), inputs(texts))
    assert lines(outcome) == (
        f"exceptions.toml: exception 5 {NEEDS}",
        f"exceptions.toml (gone/**, F401): {UNTRACKED}",
        (
            "src/a.py:1: `# noqa` silences ruff; fix: change the code so ruff"
            " passes, or, if the rule can't apply, an exception for that rule"
            " with its reason"
        ),
        (
            "pyproject.toml: tool.pytest.addopts lacks `--a`; fix: add `--a` to"
            " tool.pytest.addopts, or, if it can't apply, a"
            " `drift:tool.pytest.addopts:--a` exception with its reason"
        ),
        "Found 4 issues",
    )
    assert outcome.status == 1


def test_policy_validates_rust_exceptions() -> None:
    texts = {
        "exceptions.toml": entry("src/lib.rs", "Bad-Rule")
        + entry("src/lib.rs", "Worse-Rule")
        + entry("src/lib.rs", "clippy::a")
        + entry("gone/**", "dead_code")
        + entry("profiles/**", "drift:lints.rust.x")
        + entry("src/lib.rs", "clippy::b"),
        "Cargo.toml": "",
        "src/lib.rs": '#[expect(clippy::a, reason = "x")]\nfn f() {}\n',
    }
    outcome = run(("rust", STD, "Cargo.toml", "src/lib.rs"), inputs(texts))
    assert lines(outcome) == (
        f"exceptions.toml (src/lib.rs, Bad-Rule): {UNKNOWN}",
        f"exceptions.toml (src/lib.rs, Worse-Rule): {UNKNOWN}",
        f"exceptions.toml (gone/**, dead_code): {UNTRACKED}",
        (
            "exceptions.toml (src/lib.rs, clippy::b): no matching #[expect]"
            " attribute; fix: remove the entry"
        ),
        "Found 4 issues",
    )


def test_flaky_tests_are_named_not_tracked_paths() -> None:
    texts = {
        "exceptions.toml": entry("refresh_*", "flaky")
        + entry("x", "flaky", " "),
        "Cargo.toml": "",
    }
    outcome = run(("rust", STD, "Cargo.toml"), inputs(texts))
    assert lines(outcome) == (
        f"exceptions.toml: exception 2 {NEEDS}",
        "Found 1 issues",
    )
    python = run(
        ("python", STD), inputs({"exceptions.toml": entry("test_x", "flaky")})
    )
    assert lines(python)[0] == (f"exceptions.toml (test_x, flaky): {UNTRACKED}")


def test_policy_rejects_an_oxlint_exception_for_no_tracked_file() -> None:
    texts = {
        "exceptions.toml": entry("src/a.ts", "lint/eslint/no-bitwise")
        + entry("gone/*.ts", "lint/typescript/no-floating-promises")
    }
    outcome = run(("typescript", STD, "src/a.ts"), inputs(texts))
    assert lines(outcome) == (
        (
            "exceptions.toml (gone/*.ts, lint/typescript/no-floating-promises):"
            f" {UNTRACKED}"
        ),
        "Found 1 issues",
    )


RESOLVED = (
    "--resolved=oxlint.config.ts=/logs/project.json",
    "--resolved=typescript/oxlint.config.ts=/logs/standard.json",
)


def test_request_lists_the_resolved_configs() -> None:
    paths = request(("typescript", STD, *RESOLVED, "a.ts"), Inputs()).paths
    assert paths[-2:] == ("/logs/project.json", "/logs/standard.json")
    assert "a.ts" in paths
    assert not any(path.startswith("--") for path in paths)


def test_policy_reports_drift_between_resolved_oxlint_configs() -> None:
    texts = {
        "oxlint.config.ts": (
            'import standard from "#standards/oxlint";\n'
            "export default { extends: [standard] };\n"
        ),
        "/logs/project.json": '{"rules": {"no-bitwise": "warn"}}',
        "/logs/standard.json": '{"rules": {"no-bitwise": "deny"}}',
    }
    outcome = run(("typescript", STD, *RESOLVED), inputs(texts))
    assert lines(outcome)[0] == (
        "oxlint.config.ts: rules.eslint/no-bitwise is `warn`, weaker than"
        " `deny`; fix: set it to `deny`, or, if it can't apply, a"
        " `drift:rules.eslint/no-bitwise` exception with its reason"
    )


def test_a_resolved_config_s_file_may_hold_an_equals_sign() -> None:
    resolved = ("--resolved=oxlint.config.ts=/logs/a=b.json",)
    paths = request(("typescript", STD, *resolved), Inputs()).paths
    assert paths[-1] == "/logs/a=b.json"


def test_policy_ignores_attributes_outside_rust() -> None:
    texts = {
        "exceptions.toml": entry("a.ts", "lint/style/noVar"),
        "a.ts": '#[expect(clippy::a, reason = "x")]\n',
    }
    outcome = run(("typescript", STD, "a.ts"), inputs(texts))
    assert outcome == Outcome(FrozenList(("All checks passed",)), 0)


KNIP_NEGATIONS = FrozenOrderedDict({
    "knip.json": json.dumps({
        "project": ["**/*.ts!", "!src/**!"],
        "workspaces": {"packages/core": {"entry": ["!test/**"]}},
    })
})
NEGATED_FILES = ("src/a.ts", "packages/core/test/b.ts")


def test_a_negated_knip_pattern_fails_exceptions_naming_it() -> None:
    outcome = run(("typescript", STD, *NEGATED_FILES), inputs(KNIP_NEGATIONS))
    found = lines(outcome)
    assert outcome.status == 1
    assert len(found) == 3
    assert found[0].startswith("src/**: knip.json project negates `!src/**!`")
    workspace = "packages/core/test/**: knip.json workspaces.packages/core"
    assert found[1].startswith(f"{workspace}.entry negates `!test/**`")
    assert_lines_name_the_fix(found[:2])


def test_an_unused_exception_covers_a_negated_knip_pattern() -> None:
    texts = {
        **KNIP_NEGATIONS,
        "exceptions.toml": entry("src/**", "unused")
        + entry("packages/core/**", "unused"),
    }
    outcome = run(("typescript", STD, *NEGATED_FILES), inputs(texts))
    assert outcome == Outcome(FrozenList(("All checks passed",)), 0)
