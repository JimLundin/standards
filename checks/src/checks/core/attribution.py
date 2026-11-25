import re
from dataclasses import dataclass
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.cargo import Package, dependents, owner, relative, workspace
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    normalized,
    operands,
    option,
    options,
    parse_json,
    text,
)

ANSI = re.compile(r"\x1b\[[0-9;]*m")
COULD_NOT = r"could not (?:compile|document) `([^`]+)`"
BUILD_SCRIPT = r"failed to run custom build command for `([^ `]+)"
UNBUILT = re.compile(f"{COULD_NOT}|{BUILD_SCRIPT}")
NEXTEST_FAILURE = (
    r"^ *(?:FAIL|TIMEOUT|LEAK-FAIL|ABORT|SIG[A-Z]+) +\[ *[0-9.]+s\] +"
)
FAILED_TEST_BINARY = re.compile(
    NEXTEST_FAILURE + r"(?:\( *[0-9]+/[0-9]+\) +)?([^ :]+)", re.MULTILINE
)
EVERY_TEST_BINARY_BUILT = re.compile(
    r"^ *Starting [0-9]+ tests? across", re.MULTILINE
)
EVERY_SELECTED_TEST_RAN = re.compile(r"^ *Summary \[", re.MULTILINE)
TESTS = FrozenOrderedSet(("test", "test-release"))
CARGO_DIAGNOSTIC_START = re.compile(r"^(?=(?:error|warning)\b)", re.MULTILINE)
LOCATION = re.compile(r"^ *--> ([^ :]+):[0-9]+", re.MULTILINE)
STANDARDS_FINDING = re.compile(
    r"^([^ :]+\.(?:rs|toml)):(?:[0-9]+:)? ", re.MULTILINE
)
FOUND = "Found [0-9]+ issues"
ANALYSIS_LAST_LINE = FrozenOrderedDict({
    "core": re.compile(rf"^(?:{FOUND}|no_std: .*|no libraries)$", re.MULTILINE),
    "api": re.compile(rf"^(?:{FOUND}|All checks passed)$", re.MULTILINE),
    "shell": re.compile(
        rf"^(?:{FOUND}|no shell|shell makes [0-9]+ of [0-9]+ decisions)$",
        re.MULTILINE,
    ),
})
REACHED_ONLY_WHERE_BUILT = FrozenOrderedSet(("lint", "core"))


@dataclass(frozen=True, slots=True)
class Evidence:
    log: str
    built_artifacts: str = ""


def found(pattern: re.Pattern[str], text: str) -> FrozenList[str]:
    return FrozenList(
        name
        for match in pattern.finditer(text)
        for name in match.groups()
        if name is not None
    )


def unbuilt(block: str) -> FrozenList[str]:
    return found(UNBUILT, block)


def owners(
    paths: Sequence[str], root: str, packages: Sequence[Package]
) -> FrozenList[str]:
    found = FrozenList(owner(relative(path, root), packages) for path in paths)
    return FrozenList(package.name if package else "" for package in found)


def failed_or_unowned(
    plain: str, packages: Sequence[Package], root: str
) -> FrozenOrderedSet[str] | None:
    errors = FrozenList(
        block
        for block in CARGO_DIAGNOSTIC_START.split(plain)
        if block.startswith("error")
    )
    if any(
        not LOCATION.search(block) and not unbuilt(block) for block in errors
    ):
        return None
    members = FrozenOrderedSet(package.name for package in packages)
    broken = FrozenOrderedSet(
        name for block in errors for name in unbuilt(block)
    )
    located = FrozenList(
        path for block in errors for path in found(LOCATION, block)
    )
    named = owners((*located, *found(STANDARDS_FINDING, plain)), root, packages)
    if "" in named or any(name not in members for name in broken):
        return None
    return dependents(broken, packages) | FrozenOrderedSet(named)


def built_packages(
    artifacts: str, packages: Sequence[Package], root: str
) -> FrozenOrderedSet[str]:
    manifests = FrozenOrderedDict(
        (f"{package.path}/Cargo.toml".removeprefix("/"), package.name)
        for package in packages
    )
    records = (parse_json(line) for line in artifacts.splitlines())
    return FrozenOrderedSet(
        manifests[manifest]
        for record in records
        if record.get("reason") == "compiler-artifact"
        and (manifest := relative(str(record.get("manifest_path")), root))
        in manifests
    )


def tests_failed(
    plain: str, packages: Sequence[Package]
) -> FrozenOrderedSet[str] | None:
    if not EVERY_TEST_BINARY_BUILT.search(
        plain
    ) or not EVERY_SELECTED_TEST_RAN.search(plain):
        return None
    members = FrozenOrderedSet(package.name for package in packages)
    names = FrozenOrderedSet(found(FAILED_TEST_BINARY, plain))
    return None if any(name not in members for name in names) else names


def failed_or_unreached(
    check: str, plain: str, artifacts: str, metadata: Mapping[str, object]
) -> FrozenOrderedSet[str] | None:
    packages = workspace(metadata)
    if check in TESTS:
        return tests_failed(plain, packages)
    finished = ANALYSIS_LAST_LINE.get(check)
    if check not in REACHED_ONLY_WHERE_BUILT and finished is None:
        return None
    if finished is not None and not finished.search(plain):
        return None
    root = normalized(str(metadata.get("workspace_root")))
    failing = failed_or_unowned(plain, packages, root)
    if failing is None or check not in REACHED_ONLY_WHERE_BUILT:
        return failing
    built = built_packages(artifacts, packages, root)

    return failing | FrozenOrderedSet(
        package.name for package in packages if package.name not in built
    )


def passed(
    check: str,
    status: str,
    evidence: Evidence,
    selected: Sequence[str],
    metadata: Mapping[str, object],
) -> FrozenList[str]:
    if status == "0":
        return FrozenList(selected)
    failing = failed_or_unreached(
        check, ANSI.sub("", evidence.log), evidence.built_artifacts, metadata
    )

    if failing is None or not any(name in failing for name in selected):
        return FrozenList()
    return FrozenList(name for name in selected if name not in failing)


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(
        FrozenList((
            *operands(arguments)[2:4],
            *options(arguments, "--artifacts="),
        ))
    )


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    check, status, log, metadata, *selected = operands(arguments)
    return Outcome(
        passed(
            check,
            status,
            Evidence(
                text(inputs.texts, log),
                text(inputs.texts, option(arguments, "--artifacts=")),
            ),
            selected,
            parse_json(inputs.texts.get(metadata)),
        )
    )
