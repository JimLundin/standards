lazy from collections.abc import Sequence

import pytest
from ordered import FrozenList

from checks.core.suites import Suite, Trigger, active, load

PACKAGES = ("proto", "client", "app")
PINNED = ("NODE", "DX")
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
    loaded = load("[[suite]\n", "rust", ())
    (problem,) = loaded.problems
    assert problem.startswith("checks.toml: ")
    assert loaded.entries == ()


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
            '[[suite]]\nname = "a"\ncommand = "b\\nc"\n[[suite.when]]\ntier = "step"\n',
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
            '[[suite]]\nname = "a"\ncommand = "b"\n[[suite.when]]\ntier = "step"\npackages = "proto"\n',
            "checks.toml: suite 1 when 1 packages must be a list of strings",
        ),
        (
            '[[suite]]\nname = "a"\ncommand = "b"\n[[suite.when]]\ntier = "step"\npackages = ["ghost"]\n',
            "checks.toml: suite 1 when 1 names no workspace package `ghost`",
        ),
        (
            '[[suite]]\nname = "a"\ncommand = "b"\ntools = "NODE"\n[[suite.when]]\ntier = "step"\n',
            "checks.toml: suite 1 tools must be a list of strings",
        ),
        (
            '[[suite]]\nname = "a"\ncommand = "b"\ntools = ["NODE", "GHOST"]\n[[suite.when]]\ntier = "step"\n',
            "checks.toml: suite 1 names no pinned tool `GHOST`",
        ),
    ],
)
def test_load_reports_each_problem(text: str, problem: str) -> None:
    loaded = load(text, "rust", PACKAGES, PINNED)
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


def test_a_suite_is_active_from_the_tier_of_a_trigger() -> None:
    ip_scrub, wasm, browser = load(CONDUCTOR, "rust", PACKAGES).entries
    assert active(ip_scrub, "commit") == ip_scrub.triggers
    assert active(wasm, "release") == wasm.triggers
    assert active(browser, "commit") == ()
    assert active(browser, "step") == (
        Trigger("step", FrozenList(("crates/app/**", "crates/proto/**"))),
    )
    assert active(browser, "release") == browser.triggers


def test_every_problem_of_a_suite_is_reported() -> None:
    text = (
        '[other]\n[[suite]]\nname = "A"\ncommand = " "\nwhy = 1\nhow = 2\n'
        '[[suite]]\nname = "B"\ncommand = " "\n'
        '[[suite]]\nname = "a"\ncommand = "b"\n[[suite.when]]\ntier = "x"\n'
        'paths = "p"\npackages = ["proto"]\n'
        '[[suite.when]]\ntier = "step"\npackages = ["ghost", "proto", "spirit"]\n'
    )
    assert load(text, "rust", PACKAGES).problems == (
        "checks.toml: unknown table `other`",
        "checks.toml: suite 1 has unknown keys: how, why",
        "checks.toml: suite 2 needs a name of lowercase letters, digits and -",
        "checks.toml: suite 2 needs a command",
        "checks.toml: suite 2 needs at least one [[suite.when]]",
        "checks.toml: suite 3 when 1 needs a tier: `commit` or `step` or `release`",
        "checks.toml: suite 3 when 1 paths must be a list of strings",
        "checks.toml: suite 3 when 2 names no workspace package `ghost`",
        "checks.toml: suite 3 when 2 names no workspace package `spirit`",
    )
    rust_only = '[[suite]]\nname = "a"\ncommand = "b"\n[[suite.when]]\ntier = "x"\npaths = "p"\npackages = ["proto"]\n'
    assert load(rust_only, "python", ()).problems == (
        "checks.toml: suite 1 when 1 needs a tier: `commit` or `step` or `release`",
        "checks.toml: suite 1 when 1 paths must be a list of strings",
        "checks.toml: suite 1 when 1 packages are only for Rust projects",
    )


def test_a_repeated_name_is_found_among_all_earlier_suites() -> None:
    suite = '[[suite]]\nname = "{}"\ncommand = "{}"\n[[suite.when]]\ntier = "step"\n'
    text = (
        suite.format("a", "b") + suite.format("c", "d") + suite.format("a", " ")
    )
    assert load(text, "rust", ()).problems == (
        "checks.toml: suite 3 needs a command",
        "checks.toml: suite 3 repeats the name `a`",
    )


def test_a_suite_names_the_pinned_tools_it_runs() -> None:
    text = '[[suite]]\nname = "a"\ncommand = "b"\ntools = ["DX", "NODE"]\n[[suite.when]]\ntier = "step"\n'
    loaded = load(text, "rust", PACKAGES, PINNED)
    assert loaded.problems == ()
    assert loaded.entries[0].tools == ("DX", "NODE")
    assert load(CONDUCTOR, "rust", PACKAGES).entries[0].tools == ()
