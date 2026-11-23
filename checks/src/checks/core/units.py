import hashlib
import json
import re
from dataclasses import dataclass, field
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core import suites
from checks.core.cargo import Package, dependencies, owned, workspace
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    matches,
    operands,
    option,
    options,
    parse_json,
    posix,
    text,
)

VERSION = "1"
PROJECT = "."
# A key names the object its note annotates, so it is as long as a SHA-1
# object name.
LENGTH = 40
PIN = re.compile(r"^([A-Z_]+)=(.*)$", re.MULTILINE)
# Files no check reads: a change to them reruns no package.
DOCS = FrozenList((
    "**/*.md",
    "docs/**",
    "**/LICENSE*",
    "**/COPYING*",
    ".github/**",
))


@dataclass(frozen=True, slots=True)
class File:
    path: str
    blob: str


@dataclass(frozen=True, slots=True)
class Context:
    language: str
    standards: str
    toolchain: str
    tools: Mapping[str, str] = field(
        default_factory=FrozenOrderedDict[str, str]
    )


def digest(fields: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps([VERSION, *fields]).encode()).hexdigest()


def key(context: Context, check: str, scope: str, inputs: str) -> str:
    tool = FrozenList(
        version for name, version in context.tools.items() if name == check
    )
    fields = (context.language, check, scope, context.standards)
    return digest((*fields, context.toolchain, *tool, inputs))[:LENGTH]


def parse_record(record: str) -> File:
    stat, _, path = record.partition("\t")
    mode, blob, _stage = stat.split()
    return File(posix(path), f"{mode} {blob}")


def listing(text: str) -> FrozenList[File]:
    return FrozenList(
        parse_record(record) for record in text.split("\0") if record
    )


def fingerprint(files: Sequence[File]) -> str:
    return digest(FrozenList(f"{file.blob} {file.path}" for file in files))


def any_match(file: str, globs: Sequence[str]) -> bool:
    return any(matches(file, glob) for glob in globs)


def package_inputs(
    files: Sequence[File], packages: Sequence[Package]
) -> FrozenOrderedDict[str, str]:
    """Each package's files and its workspace dependencies', with every
    file outside the packages and the docs, such as Cargo.lock."""
    owners = FrozenOrderedDict(
        (file.path, owned(file.path, packages)) for file in files
    )
    grouped = FrozenOrderedDict(
        (name, FrozenList(file for file in files if owners[file.path] == name))
        for name in ("", *(package.name for package in packages))
    )
    common = fingerprint(
        FrozenList(
            file for file in grouped[""] if not any_match(file.path, DOCS)
        )
    )
    return FrozenOrderedDict(
        (
            package.name,
            digest((
                common,
                *(
                    fingerprint(grouped[name])
                    for name in dependencies(
                        FrozenOrderedSet((package.name,)), packages
                    )
                ),
            )),
        )
        for package in packages
    )


def pins_of(text: str) -> FrozenOrderedDict[str, str]:
    """The `NAME=version` lines of a tools.env."""
    return FrozenOrderedDict(PIN.findall(text))


def suite_inputs(
    triggers: Sequence[suites.Trigger],
    files: Sequence[File],
    packages: Mapping[str, str],
    tools: Sequence[str],
) -> str:
    """The files a suite's triggers name, the inputs of the packages they
    name, or every file when one names neither, with the pins of its tools."""
    if any(not trigger.paths and not trigger.packages for trigger in triggers):
        return digest((fingerprint(files), *tools))
    globs = FrozenList(glob for trigger in triggers for glob in trigger.paths)
    named = FrozenList(
        name for trigger in triggers for name in trigger.packages
    )
    return digest((
        fingerprint(
            FrozenList(file for file in files if any_match(file.path, globs))
        ),
        *(packages[name] for name in named),
        *tools,
    ))


def checks_of(arguments: Sequence[str], prefix: str) -> FrozenList[str]:
    return FrozenList(
        check
        for value in options(arguments, prefix)
        for check in value.split(",")
        if check
    )


def described(arguments: Sequence[str], inputs: Inputs) -> FrozenList[Package]:
    metadata = option(arguments, "--metadata=")
    if not metadata:
        return FrozenList()
    return workspace(parse_json(inputs.texts.get(metadata)))


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request(
        FrozenList((
            operands(arguments)[2],
            suites.SUITES,
            *options(arguments, "--metadata="),
            *options(arguments, "--pins="),
        ))
    )


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    language, tier, listed = operands(arguments)
    context = Context(
        language,
        option(arguments, "--standards="),
        option(arguments, "--toolchain="),
        FrozenOrderedDict(
            (name, version)
            for name, _, version in (
                tool.partition("=") for tool in options(arguments, "--tool=")
            )
        ),
    )
    files = listing(text(inputs.texts, listed))
    packages = described(arguments, inputs)
    whole = fingerprint(files)
    scoped = package_inputs(files, packages)
    names = FrozenList(package.name for package in packages)
    pins = pins_of(text(inputs.texts, option(arguments, "--pins=")))
    loaded = suites.load(
        inputs.texts.get(suites.SUITES), language, names, FrozenList(pins)
    )
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
                    suite_inputs(
                        triggers,
                        files,
                        scoped,
                        FrozenList(
                            f"{tool}={pins[tool]}" for tool in suite.tools
                        ),
                    ),
                )
                for suite, triggers in chosen
            ),
            *(f"package\t{name}" for name in names),
            *(f"suite\t{suite.name}\t{suite.command}" for suite, _ in chosen),
            *(f"problem\t{problem}" for problem in loaded.problems),
        )),
        1 if loaded.problems else 0,
    )
