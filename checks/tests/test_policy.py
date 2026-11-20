lazy from collections.abc import Mapping

from ordered import FrozenList, FrozenOrderedDict

from checks.core.policy import request, run
from checks.core.values import Inputs, Outcome, Request

STD = "C:/standards"
RETIRED = (
    "`std` is no longer an exception; "
    'declare `[package.metadata.standards] layer = "shell"`'
)


def entry(path: str, rule: str, reason: str = "r") -> str:
    return f'[[exception]]\npath = "{path}"\nrule = "{rule}"\nreason = "{reason}"\n'


def inputs(texts: Mapping[str, str]) -> Inputs:
    return Inputs(FrozenOrderedDict(texts))


def lines(outcome: Outcome) -> FrozenList[str]:
    return outcome.lines


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
        "exceptions.toml: exception 5 needs a path, a rule and a reason",
        "exceptions.toml (gone/**, F401): path matches no tracked file",
        "src/a.py:1: suppression `# noqa`; add an entry to exceptions.toml instead",
        "pyproject.toml: tool.pytest.addopts lacks `--a` (exception rule `drift:tool.pytest.addopts:--a`)",
        "Found 4 issues",
    )
    assert outcome.status == 1


def test_policy_validates_rust_exceptions() -> None:
    texts = {
        "exceptions.toml": entry("src/lib.rs", "Bad-Rule")
        + entry("src/lib.rs", "Worse-Rule")
        + entry("src/lib.rs", "clippy::a")
        + entry("gone/**", "dead_code")
        + entry("src/lib.rs", "std")
        + entry("Cargo.toml", "std")
        + entry("profiles/**", "drift:lints.rust.x")
        + entry("src/lib.rs", "clippy::b"),
        "Cargo.toml": "",
        "src/lib.rs": '#[expect(clippy::a, reason = "x")]\nfn f() {}\n',
    }
    outcome = run(("rust", STD, "Cargo.toml", "src/lib.rs"), inputs(texts))
    assert lines(outcome) == (
        "exceptions.toml (src/lib.rs, Bad-Rule): unknown rule for rust",
        "exceptions.toml (src/lib.rs, Worse-Rule): unknown rule for rust",
        "exceptions.toml (gone/**, dead_code): path matches no tracked file",
        f"exceptions.toml (src/lib.rs, std): {RETIRED} in src/lib.rs instead",
        f"exceptions.toml (Cargo.toml, std): {RETIRED} in Cargo.toml instead",
        "exceptions.toml (src/lib.rs, clippy::b): no matching #[expect] attribute; remove the entry",
        "Found 6 issues",
    )


def test_flaky_tests_are_named_not_tracked_paths() -> None:
    texts = {
        "exceptions.toml": entry("refresh_*", "flaky")
        + entry("x", "flaky", " "),
        "Cargo.toml": "",
    }
    outcome = run(("rust", STD, "Cargo.toml"), inputs(texts))
    assert lines(outcome) == (
        "exceptions.toml: exception 2 needs a path, a rule and a reason",
        "Found 1 issues",
    )
    python = run(
        ("python", STD), inputs({"exceptions.toml": entry("test_x", "flaky")})
    )
    assert lines(python)[0] == (
        "exceptions.toml (test_x, flaky): path matches no tracked file"
    )


def test_policy_ignores_attributes_outside_rust() -> None:
    texts = {
        "exceptions.toml": entry("a.ts", "lint/style/noVar"),
        "a.ts": '#[expect(clippy::a, reason = "x")]\n',
    }
    outcome = run(("typescript", STD, "a.ts"), inputs(texts))
    assert outcome == Outcome(FrozenList(("All checks passed",)), 0)
