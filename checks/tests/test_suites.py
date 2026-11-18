lazy from collections.abc import Sequence

import pytest
from ordered import FrozenList

from checks.core.suites import Changes, Suite, Trigger, load, triggered

PACKAGES = ("proto", "client", "app")
CONDUCTOR = """
[[suite]]
name = "ip-scrub"
command = "tools/scrub.sh --check"
[[suite.when]]
tier = "commit"
paths = ["docs/**/*.txt", "tools/scrub-ips.py"]

[[suite]]
name = "wasm-clippy"
command = "tools/wasm-clippy.sh"
[[suite.when]]
tier = "commit"
packages = ["proto", "app"]

[[suite]]
name = "browser"
command = "tools/e2e-browser.sh"
[[suite.when]]
tier = "release"
[[suite.when]]
tier = "step"
paths = ["crates/app/**", "crates/proto/**"]
"""


def changes(*files: str, packages: Sequence[str] = ()) -> Changes:
    return Changes(FrozenList(files), FrozenList(packages))


def names(suites: Sequence[Suite]) -> FrozenList[str]:
    return FrozenList(suite.name for suite in suites)


def test_load_parses_suites_in_order() -> None:
    loaded = load(CONDUCTOR, "rust", PACKAGES)
    assert loaded.problems == ()
    assert loaded.entries[0] == Suite(
        "ip-scrub",
        "tools/scrub.sh --check",
        FrozenList((
            Trigger(
                "commit", FrozenList(("docs/**/*.txt", "tools/scrub-ips.py"))
            ),
        )),
    )
    assert loaded.entries[1].triggers == (
        Trigger("commit", packages=FrozenList(("proto", "app"))),
    )
    assert names(loaded.entries) == ("ip-scrub", "wasm-clippy", "browser")


def test_load_without_a_file_has_no_suites() -> None:
    loaded = load(None, "python", ())
    assert loaded.entries == ()
    assert loaded.problems == ()


def test_load_reports_invalid_toml() -> None:
    (problem,) = load("[[suite]\n", "rust", ()).problems
    assert problem.startswith("checks.toml: ")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("[other]\n", "checks.toml: unknown table `other`"),
        (
            '[[suite]]\nname = "a"\ncommand = "b"\nextra = 1\n',
            "checks.toml: suite 1 has unknown keys: extra",
        ),
        (
            '[[suite]]\nname = "A b"\ncommand = "b"\n[[suite.when]]\ntier = "step"\n',
            "checks.toml: suite 1 needs a name of lowercase letters, digits and -",
        ),
        (
            '[[suite]]\nname = "a"\ncommand = " "\n[[suite.when]]\ntier = "step"\n',
            "checks.toml: suite 1 needs a command",
        ),
        (
            '[[suite]]\nname = "a"\ncommand = "b\\tc"\n[[suite.when]]\ntier = "step"\n',
            "checks.toml: suite 1 command must be one line without tabs",
        ),
        (
            '[[suite]]\nname = "a"\ncommand = "b"\n',
            "checks.toml: suite 1 needs at least one [[suite.when]]",
        ),
        (
            '[[suite]]\nname = "a"\ncommand = "b"\n[[suite.when]]\ntier = "fast"\n',
            "checks.toml: suite 1 when 1 needs a tier: `commit` or `step` or `release`",
        ),
        (
            '[[suite]]\nname = "a"\ncommand = "b"\n[[suite.when]]\ntier = "step"\nwhy = 1\n',
            "checks.toml: suite 1 when 1 has unknown keys: why",
        ),
        (
            '[[suite]]\nname = "a"\ncommand = "b"\n[[suite.when]]\ntier = "step"\npaths = "x"\n',
            "checks.toml: suite 1 when 1 paths must be a list of strings",
        ),
        (
            '[[suite]]\nname = "a"\ncommand = "b"\n[[suite.when]]\ntier = "step"\npaths = [""]\n',
            "checks.toml: suite 1 when 1 paths must be a list of strings",
        ),
        (
            '[[suite]]\nname = "a"\ncommand = "b"\n[[suite.when]]\ntier = "step"\npackages = ["ghost"]\n',
            "checks.toml: suite 1 when 1 names no workspace package `ghost`",
        ),
    ],
)
def test_load_reports_each_problem(text: str, problem: str) -> None:
    loaded = load(text, "rust", PACKAGES)
    assert loaded.problems == (problem,)
    assert loaded.entries == ()


def test_packages_are_only_for_rust() -> None:
    text = '[[suite]]\nname = "a"\ncommand = "b"\n[[suite.when]]\ntier = "step"\npackages = ["proto"]\n'
    assert load(text, "python", ()).problems == (
        "checks.toml: suite 1 when 1 packages are only for Rust projects",
    )


def test_repeated_names_are_reported_and_the_first_kept() -> None:
    suite = (
        '[[suite]]\nname = "a"\ncommand = "{}"\n[[suite.when]]\ntier = "step"\n'
    )
    loaded = load(suite.format("first") + suite.format("second"), "rust", ())
    assert loaded.problems == ("checks.toml: suite 2 repeats the name `a`",)
    assert names(loaded.entries) == ("a",)
    assert loaded.entries[0].command == "first"


def test_a_suite_runs_in_its_tier_and_above_when_its_paths_change() -> None:
    suites = load(CONDUCTOR, "rust", PACKAGES).entries
    record = changes("docs/p1/run.txt")
    assert names(triggered(suites, "commit", record)) == ("ip-scrub",)
    assert names(triggered(suites, "release", record)) == (
        "ip-scrub",
        "browser",
    )
    assert names(triggered(suites, "step", changes("docs/notes.md"))) == ()


def test_a_package_trigger_fires_for_affected_packages() -> None:
    suites = load(CONDUCTOR, "rust", PACKAGES).entries
    affected = changes("crates/agents/src/lib.rs", packages=("agents", "app"))
    assert names(triggered(suites, "commit", affected)) == ("wasm-clippy",)
    unrelated = changes("crates/agents/src/lib.rs", packages=("agents",))
    assert names(triggered(suites, "commit", unrelated)) == ()


def test_the_step_trigger_is_explicit() -> None:
    suites = load(CONDUCTOR, "rust", PACKAGES).entries
    proto = changes("crates/proto/src/lib.rs", packages=("proto", "app"))
    assert names(triggered(suites, "commit", proto)) == ("wasm-clippy",)
    assert names(triggered(suites, "step", proto)) == ("wasm-clippy", "browser")
    home = changes("crates/home/src/lib.rs", packages=("home",))
    assert names(triggered(suites, "step", home)) == ()
    assert names(triggered(suites, "release", home)) == ("browser",)


def test_a_trigger_without_paths_fires_on_any_change() -> None:
    suites = load(CONDUCTOR, "rust", PACKAGES).entries
    assert names(triggered(suites, "release", changes())) == ()
    assert names(triggered(suites, "release", changes("README.md"))) == (
        "browser",
    )


def test_everything_fires_every_trigger_up_to_the_tier() -> None:
    suites = load(CONDUCTOR, "rust", PACKAGES).entries
    everything = Changes(FrozenList(), FrozenList(), everything=True)
    assert names(triggered(suites, "commit", everything)) == (
        "ip-scrub",
        "wasm-clippy",
    )
    assert names(triggered(suites, "step", everything)) == (
        "ip-scrub",
        "wasm-clippy",
        "browser",
    )
