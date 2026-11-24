from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.drift import DRIFT, PROJECT_FILES, STANDARD_FILES, Snapshot
from checks.core.exceptions import (
    EXCEPTIONS,
    Exceptions,
    exceptions_in,
    kind,
    validate,
)
from checks.core.slop import rule_file
from checks.core.structure import CODES
from checks.core.suppressions import is_source, suppressions, used_attributes
from checks.core.values import Inputs, Outcome, Request, summarized

if TYPE_CHECKING:
    from collections.abc import Sequence


def project_paths(language: str, files: Sequence[str]) -> FrozenList[str]:
    return FrozenList(
        dict.fromkeys((
            EXCEPTIONS,
            *PROJECT_FILES[language],
            *(file for file in files if is_source(language, file)),
        ))
    )


def snapshot_of(
    language: str, standards: str, files: Sequence[str], inputs: Inputs
) -> Snapshot:
    project = FrozenOrderedDict(
        (path, text)
        for path in project_paths(language, files)
        if (text := inputs.texts.get(path)) is not None
    )
    shared = FrozenOrderedDict(
        (path, text)
        for path in STANDARD_FILES[language]
        if (text := inputs.texts.get(f"{standards}/{path}")) is not None
    )
    return Snapshot(FrozenList(files), project, shared)


def slop_rules(language: str, exceptions: Exceptions) -> FrozenOrderedSet[str]:
    return FrozenOrderedSet(
        entry.rule
        for entry in exceptions.entries
        if kind(language, entry.rule) == "slop"
    )


def request(arguments: Sequence[str], inputs: Inputs) -> Request:
    language, standards, *files = arguments
    shared = (f"{standards}/{path}" for path in STANDARD_FILES[language])
    definitions = (
        rule_file(standards, rule)
        for rule in slop_rules(language, exceptions_in(inputs))
    )
    return Request(
        FrozenList((*project_paths(language, files), *shared, *definitions))
    )


def defined(
    language: str, standards: str, exceptions: Exceptions, inputs: Inputs
) -> FrozenList[str]:
    slop = (
        rule
        for rule in slop_rules(language, exceptions)
        if rule_file(standards, rule) in inputs.texts
    )
    return FrozenList((*CODES, *slop))


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    language, standards, *files = arguments
    snapshot = snapshot_of(language, standards, files, inputs)
    exceptions = exceptions_in(inputs)
    attributes = used_attributes(snapshot.project)
    drifted = FrozenList(
        issue
        for issue in DRIFT[language](snapshot)
        if not exceptions.covers(issue.rule, issue.path)
    )
    issues = (
        *validate(
            language,
            exceptions,
            snapshot.files,
            attributes,
            defined(language, standards, exceptions, inputs),
        ),
        *suppressions(language, snapshot.project, exceptions),
        *drifted,
    )
    return summarized(
        FrozenList(f"{issue.path}: {issue.message}" for issue in issues)
    )
