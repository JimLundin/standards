import hashlib
import json
from dataclasses import dataclass
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core import suites
from checks.core.scope import (
    DOCS,
    Package,
    any_match,
    dependencies,
    owned,
    workspace,
)
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    operands,
    options,
    parse_json,
    posix,
)

VERSION = "1"
PROJECT = "."
# A key names the object its note annotates, so it is as long as a SHA-1
# object name.
LENGTH = 40


@dataclass(frozen=True, slots=True)
class File:
    path: str
    blob: str


@dataclass(frozen=True, slots=True)
class Context:
    language: str
    standards: str
    toolchain: str


def digest(fields: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps([VERSION, *fields]).encode()).hexdigest()


def key(context: Context, check: str, scope: str, inputs: str) -> str:
    fields = (context.language, check, scope)
    return digest((*fields, context.standards, context.toolchain, inputs))[
        :LENGTH
    ]


def parse_record(record: str) -> File:
    stat, _, path = record.partition("\t")
    mode, blob, _stage = stat.split(" ")
    return File(posix(path), f"{mode} {blob}")


def listing(text: str) -> FrozenList[File]:
    return FrozenList(
        parse_record(record) for record in text.split("\0") if record
    )


def fingerprint(files: Sequence[File]) -> str:
    return digest(FrozenList(f"{file.blob} {file.path}" for file in files))


def package_inputs(
    files: Sequence[File], packages: Sequence[Package]
) -> FrozenOrderedDict[str, str]:
    owners = FrozenOrderedDict(
        (file.path, owned(file.path, packages)) for file in files
    )
    common = fingerprint(
        FrozenList(
            file
            for file in files
            if not owners[file.path] and not any_match(file.path, DOCS)
        )
    )
    closures = FrozenOrderedDict(
        (
            package.name,
            dependencies(FrozenOrderedSet((package.name,)), packages),
        )
        for package in packages
    )
    return FrozenOrderedDict(
        (
            name,
            digest((
                common,
                fingerprint(
                    FrozenList(
                        file for file in files if owners[file.path] in closure
                    )
                ),
            )),
        )
        for name, closure in closures.items()
    )


def suite_inputs(
    triggers: Sequence[suites.Trigger],
    files: Sequence[File],
    packages: Mapping[str, str],
) -> str:
    if any(not trigger.paths and not trigger.packages for trigger in triggers):
        return fingerprint(files)
    globs = FrozenList(glob for trigger in triggers for glob in trigger.paths)
    named = FrozenList(
        name for trigger in triggers for name in trigger.packages
    )
    return digest((
        fingerprint(
            FrozenList(file for file in files if any_match(file.path, globs))
        ),
        *(packages.get(name, "") for name in named),
    ))


def checks_of(arguments: Sequence[str], prefix: str) -> FrozenList[str]:
    return FrozenList(
        check
        for value in options(arguments, prefix)
        for check in value.split(",")
        if check
    )


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(
        FrozenList((
            operands(arguments)[2],
            suites.SUITES,
            *options(arguments, "--metadata="),
        ))
    )


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    language, tier, listed = operands(arguments)
    context = Context(
        language,
        "".join(options(arguments, "--standards=")),
        "".join(options(arguments, "--toolchain=")),
    )
    files = listing(inputs.texts.get(listed, ""))
    metadata = options(arguments, "--metadata=")
    packages = (
        workspace(parse_json(inputs.texts.get(metadata[0])))
        if metadata
        else FrozenList()
    )
    whole = fingerprint(files)
    scoped = package_inputs(files, packages)
    names = FrozenList(package.name for package in packages)
    loaded = suites.load(inputs.texts.get(suites.SUITES), language, names)
    chosen = FrozenList(
        (suite, triggers)
        for suite in loaded.entries
        if (triggers := suites.active(suite, tier))
    )
    return Outcome(
        FrozenList((
            *(
                f"unit\t{check}\t{PROJECT}\t{key(context, check, PROJECT, whole)}"
                for check in checks_of(arguments, "--project=")
            ),
            *(
                f"unit\t{check}\t{name}\t{key(context, check, name, inputs)}"
                for check in checks_of(arguments, "--package=")
                for name, inputs in scoped.items()
            ),
            *(
                f"unit\tsuite\t{suite.name}\t"
                + key(
                    context,
                    f"suite {suite.command}",
                    suite.name,
                    suite_inputs(triggers, files, scoped),
                )
                for suite, triggers in chosen
            ),
            *(f"package\t{name}" for name in names),
            *(f"suite\t{suite.name}\t{suite.command}" for suite, _ in chosen),
            *(f"problem\t{problem}" for problem in loaded.problems),
        )),
        1 if loaded.problems else 0,
    )
