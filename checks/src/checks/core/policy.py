from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict

from checks.core.drift import DRIFT, PROJECT_FILES, STANDARD_FILES, Snapshot
from checks.core.suppressions import is_source, suppressions, used_attributes
from checks.core.values import Inputs, Outcome, Request, matches, summarized
from checks.core.waivers import EXCEPTIONS, Issue, Waiver, kind, load, waived

if TYPE_CHECKING:
    from collections.abc import Sequence

SHELL = '`[package.metadata.standards] layer = "shell"`'
UNPATHED = ("drift", "flaky")


def waiver_issues(
    language: str, waivers: Sequence[Waiver], snapshot: Snapshot
) -> FrozenList[Issue]:
    issues: FrozenList[Issue] = FrozenList()
    for waiver in waivers:
        rule_kind = kind(language, waiver.rule)
        where = f"{EXCEPTIONS} ({waiver.path}, {waiver.rule})"
        matched = FrozenList(
            file for file in snapshot.files if matches(file, waiver.path)
        )
        if language == "rust" and waiver.rule == "std":
            message = (
                "`std` is no longer an exception; "
                f"declare {SHELL} in {waiver.path} instead"
            )
            issues += (Issue(where, message),)
        elif not rule_kind:
            issues += (Issue(where, f"unknown rule for {language}"),)
        elif rule_kind not in UNPATHED and not matched:
            issues += (Issue(where, "path matches no tracked file"),)
        elif rule_kind == "attribute" and not any(
            (file, waiver.rule) in used_attributes(snapshot.project)
            for file in matched
        ):
            message = "no matching #[expect] attribute; remove the entry"
            issues += (Issue(where, message),)
    return issues


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
    waivers = load(inputs.texts.get(EXCEPTIONS))
    drifted = FrozenList(
        issue
        for issue in DRIFT[language](snapshot)
        if not waived(waivers.entries, issue.path, issue.rule)
    )
    issues = (
        *waivers.problems,
        *waiver_issues(language, waivers.entries, snapshot),
        *suppressions(language, snapshot.project, waivers.entries),
        *drifted,
    )
    return summarized(
        FrozenList(f"{issue.path}: {issue.message}" for issue in issues)
    )
