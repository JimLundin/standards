from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict

from checks.core.cargo import library_files
from checks.core.comment_rule import comment_issues
from checks.core.comments import is_source
from checks.core.drift import DRIFT, PROJECT_FILES, STANDARD_FILES, Snapshot
from checks.core.exceptions import EXCEPTIONS, exceptions_in, validate
from checks.core.suppressions import suppressions, used_attributes
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    operands,
    option,
    options,
    parse_json,
    summarized,
)

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


# Each `--resolved=<config>=<file>` names a file holding a config, the
# project's or a standard's, as its tool resolves it.
def resolved_files(arguments: Sequence[str]) -> FrozenOrderedDict[str, str]:
    return FrozenOrderedDict(
        (config, file)
        for option in options(arguments, "--resolved=")
        for config, _, file in (option.partition("="),)
    )


def snapshot_of(arguments: Sequence[str], inputs: Inputs) -> Snapshot:
    language, standards, *files = operands(arguments)
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
    resolved = FrozenOrderedDict(
        (config, text)
        for config, file in resolved_files(arguments).items()
        if (text := inputs.texts.get(file)) is not None
    )
    return Snapshot(FrozenList(files), project, shared, resolved)


def metadata_file(arguments: Sequence[str]) -> FrozenList[str]:
    found = option(arguments, "--metadata=")
    return FrozenList((found,) if found else ())


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    language, standards, *files = operands(arguments)
    shared = (f"{standards}/{path}" for path in STANDARD_FILES[language])
    return Request(
        FrozenList((
            *project_paths(language, files),
            *shared,
            *resolved_files(arguments).values(),
            *metadata_file(arguments),
        ))
    )


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    language = operands(arguments)[0]
    snapshot = snapshot_of(arguments, inputs)
    exceptions = exceptions_in(inputs)
    attributes = used_attributes(snapshot.project)
    libraries = library_files(
        parse_json(inputs.texts.get(option(arguments, "--metadata="))),
        snapshot.files,
    )
    drifted = FrozenList(
        issue
        for issue in DRIFT[language](snapshot)
        if not exceptions.covers(issue.rule, issue.path)
    )
    issues = (
        *validate(language, exceptions, snapshot.files, attributes),
        *suppressions(language, snapshot.project, exceptions),
        *comment_issues(language, snapshot.project, exceptions, libraries),
        *drifted,
    )
    return summarized(
        FrozenList(f"{issue.path}: {issue.message}" for issue in issues)
    )
