import re
lazy from collections.abc import Sequence

from ordered import FrozenList, FrozenOrderedSet

from checks.core.scope import Package, dependents, workspace
from checks.core.values import Inputs, Outcome, Request, operands, parse_json

ANSI = re.compile(r"\x1b\[[0-9;]*m")
UNCOMPILED = re.compile(r"could not compile `([^`]+)`")
# nextest's line for a failed test names its binary, `package` or
# `package::binary`; retries print `TRY n FAIL` and are not failures.
STATUS = r"^ *(?:FAIL|TIMEOUT|LEAK-FAIL|ABORT|SIG[A-Z]+) +\[ *[0-9.]+s\] +"
FAILED_TEST = re.compile(
    STATUS + r"(?:\( *[0-9]+/[0-9]+\) +)?([^ :]+)", re.MULTILINE
)


def failed(log: str, packages: Sequence[Package]) -> FrozenOrderedSet[str]:
    plain = ANSI.sub("", log)
    members = FrozenOrderedSet(package.name for package in packages)
    uncompiled = FrozenOrderedSet(UNCOMPILED.findall(plain)) & members
    tested = FrozenOrderedSet(FAILED_TEST.findall(plain)) & members
    return dependents(uncompiled, packages) | tested


def passed(
    status: str, log: str, selected: Sequence[str], packages: Sequence[Package]
) -> FrozenList[str]:
    if status == "0":
        return FrozenList(selected)
    failures = failed(log, packages)
    if not any(name in failures for name in selected):
        return FrozenList()
    return FrozenList(name for name in selected if name not in failures)


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList(operands(arguments)[1:3]))


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    status, log, metadata, *selected = operands(arguments)
    packages = workspace(parse_json(inputs.texts.get(metadata)))
    return Outcome(
        passed(status, inputs.texts.get(log, ""), selected, packages)
    )
