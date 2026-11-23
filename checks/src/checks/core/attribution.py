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
# nextest's line for a failed test names its binary, `package` or
# `package::binary`; retries print `TRY n FAIL` and are not failures.
STATUS = r"^ *(?:FAIL|TIMEOUT|LEAK-FAIL|ABORT|SIG[A-Z]+) +\[ *[0-9.]+s\] +"
FAILED_TEST = re.compile(
    STATUS + r"(?:\( *[0-9]+/[0-9]+\) +)?([^ :]+)", re.MULTILINE
)
# nextest starts running only once every test binary built, and prints its
# summary only once every selected test ran; cargo test prints neither.
STARTED = re.compile(r"^ *Starting [0-9]+ tests? across", re.MULTILINE)
SUMMARY = re.compile(r"^ *Summary \[", re.MULTILINE)
TESTS = FrozenOrderedSet(("test", "test-release"))
# A cargo diagnostic starts `error` or `warning`; only an error fails.
DIAGNOSTIC = re.compile(r"^(?=(?:error|warning)\b)", re.MULTILINE)
LOCATION = re.compile(r"^ *--> ([^ :]+):[0-9]+", re.MULTILINE)
# The standards' own checks print `path:line: finding` or `path: finding`.
FINDING = re.compile(r"^([^ :]+\.(?:rs|toml)):(?:[0-9]+:)? ", re.MULTILINE)
FOUND = "Found [0-9]+ issues"
# The last line of each analysis, printed only once it has read everything.
FINISHED = FrozenOrderedDict({
    "core": re.compile(rf"^(?:{FOUND}|no_std: .*|no libraries)$", re.MULTILINE),
    "api": re.compile(rf"^(?:{FOUND}|All checks passed)$", re.MULTILINE),
    "shell": re.compile(
        rf"^(?:{FOUND}|no shell|shell makes [0-9]+ of [0-9]+ decisions)$",
        re.MULTILINE,
    ),
})
# The checks that reach a package only where cargo built one of its targets.
BUILT = FrozenOrderedSet(("lint", "core"))


@dataclass(frozen=True, slots=True)
class Evidence:
    """A run's log, and cargo's JSON messages of what it built."""

    log: str
    artifacts: str = ""


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


def failed(
    plain: str, packages: Sequence[Package], root: str
) -> FrozenOrderedSet[str] | None:
    """The packages a log's errors and findings fail, or None where one of
    them belongs to no package of the workspace."""
    errors = FrozenList(
        block for block in DIAGNOSTIC.split(plain) if block.startswith("error")
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
    named = owners((*located, *found(FINDING, plain)), root, packages)
    if "" in named or any(name not in members for name in broken):
        return None
    return dependents(broken, packages) | FrozenOrderedSet(named)


def reached(
    artifacts: str, packages: Sequence[Package], root: str
) -> FrozenOrderedSet[str]:
    """The packages cargo built a target of, by the manifest its JSON
    messages name."""
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
    if not STARTED.search(plain) or not SUMMARY.search(plain):
        return None
    members = FrozenOrderedSet(package.name for package in packages)
    names = FrozenOrderedSet(found(FAILED_TEST, plain))
    return None if any(name not in members for name in names) else names


def failures(
    check: str, plain: str, artifacts: str, metadata: Mapping[str, object]
) -> FrozenOrderedSet[str] | None:
    """The packages a failed run failed or never reached; None where its log
    can't tell them apart."""
    packages = workspace(metadata)
    if check in TESTS:
        return tests_failed(plain, packages)
    finished = FINISHED.get(check)
    if check not in BUILT and finished is None:
        return None
    if finished is not None and not finished.search(plain):
        return None
    root = normalized(str(metadata.get("workspace_root")))
    failing = failed(plain, packages, root)
    if failing is None or check not in BUILT:
        return failing
    built = reached(artifacts, packages, root)
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
    failing = failures(
        check, ANSI.sub("", evidence.log), evidence.artifacts, metadata
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
