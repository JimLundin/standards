from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict

from checks.core.drift import DRIFT, PROJECT_FILES, STANDARD_FILES, Snapshot
from checks.core.exceptions import EXCEPTIONS, exceptions_in, validate
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


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    language, standards, *files = arguments
    shared = (f"{standards}/{path}" for path in STANDARD_FILES[language])
    return Request(FrozenList((*project_paths(language, files), *shared)))


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
        *validate(language, exceptions, snapshot.files, attributes),
        *suppressions(language, snapshot.project, exceptions),
        *drifted,
    )
    return summarized(
        FrozenList(f"{issue.path}: {issue.message}" for issue in issues)
    )
