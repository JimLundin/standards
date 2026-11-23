import re
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedSet

from checks.core.cargo import Package, dependents, owner, relative, workspace
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    normalized,
    operands,
    parse_json,
    text,
)

ANSI = re.compile(r"\x1b\[[0-9;]*m")
UNBUILT = re.compile(r"could not (?:compile|document) `([^`]+)`")
# nextest's line for a failed test names its binary, `package` or
# `package::binary`; retries print `TRY n FAIL` and are not failures.
STATUS = r"^ *(?:FAIL|TIMEOUT|LEAK-FAIL|ABORT|SIG[A-Z]+) +\[ *[0-9.]+s\] +"
FAILED_TEST = re.compile(
    STATUS + r"(?:\( *[0-9]+/[0-9]+\) +)?([^ :]+)", re.MULTILINE
)
# A cargo diagnostic starts `error` or `warning`; only an error's location
# fails its package.
DIAGNOSTIC = re.compile(r"^(?=(?:error|warning)\b)", re.MULTILINE)
LOCATION = re.compile(r"^ *--> ([^ :]+):[0-9]+", re.MULTILINE)
# The standards' own checks print `path:line: finding` or `path: finding`.
FINDING = re.compile(r"^([^ :]+\.(?:rs|toml)):(?:[0-9]+:)? ", re.MULTILINE)


def located(plain: str) -> FrozenList[str]:
    errors = FrozenList(
        path
        for block in DIAGNOSTIC.split(plain)
        if block.startswith("error")
        for path in map(str, LOCATION.findall(block))
    )
    return errors + FrozenList(FINDING.findall(plain))


def owners(
    paths: Sequence[str], root: str, packages: Sequence[Package]
) -> FrozenList[str]:
    found = FrozenList(owner(relative(path, root), packages) for path in paths)
    return FrozenList(package.name if package else "" for package in found)


def failed(
    log: str, metadata: Mapping[str, object]
) -> FrozenOrderedSet[str] | None:
    packages = workspace(metadata)
    plain = ANSI.sub("", log)
    root = normalized(str(metadata.get("workspace_root")))
    named = owners(located(plain), root, packages)
    if "" in named:
        return None
    members = FrozenOrderedSet(package.name for package in packages)
    unbuilt = FrozenOrderedSet(UNBUILT.findall(plain)) & members
    tested = FrozenOrderedSet(FAILED_TEST.findall(plain)) & members
    return dependents(unbuilt, packages) | tested | FrozenOrderedSet(named)


def passed(
    status: str,
    log: str,
    selected: Sequence[str],
    metadata: Mapping[str, object],
) -> FrozenList[str]:
    if status == "0":
        return FrozenList(selected)
    failures = failed(log, metadata)
    if failures is None or not any(name in failures for name in selected):
        return FrozenList()
    return FrozenList(name for name in selected if name not in failures)


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList(operands(arguments)[1:3]))


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    status, log, metadata, *selected = operands(arguments)
    return Outcome(
        passed(
            status,
            text(inputs.texts, log),
            selected,
            parse_json(inputs.texts.get(metadata)),
        )
    )
