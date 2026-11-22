import hashlib
import json
from dataclasses import dataclass, field
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core import manifests, suites
from checks.core.scope import (
    DOCS,
    Package,
    any_match,
    dependencies,
    owned,
    workspace,
)
from checks.core.values import (
    EMPTY,
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
LOCKFILE = "Cargo.lock"
MANIFEST = "Cargo.toml"


@dataclass(frozen=True, slots=True)
class File:
    path: str
    blob: str


@dataclass(frozen=True, slots=True)
class Workspace:
    packages: Sequence[Package]
    # Parsed manifests by path, the root's included; empty when any of
    # them can't be read, so every manifest counts as its blob.
    manifests: Mapping[str, Mapping[str, object]]
    # Each package's resolved dependencies outside the workspace; None
    # without a resolve graph, so the lockfile counts as its blob.
    locks: Mapping[str, Sequence[str]] | None


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
    tool = context.tools.get(check, "")
    fields = (context.language, check, scope, context.standards)
    return digest((*fields, context.toolchain, tool, inputs))[:LENGTH]


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


def manifest_of(package: Package) -> str:
    return f"{package.path}/{MANIFEST}" if package.path else MANIFEST


def counted(file: File, workspace: Workspace) -> bool:
    return file.path != LOCKFILE or workspace.locks is None


def seen(file: File, owner: Package, workspace: Workspace) -> str:
    manifest = workspace.manifests.get(file.path)
    if manifest is None or file.path != manifest_of(owner):
        return f"{file.blob} {file.path}"
    return digest(manifests.published(manifest))


def common_inputs(
    unowned: Sequence[File], root: Mapping[str, object] | None
) -> str:
    return digest((
        fingerprint(
            FrozenList(
                file
                for file in unowned
                if not any_match(file.path, DOCS)
                and (root is None or file.path != MANIFEST)
            )
        ),
        *(manifests.shared(root) if root is not None else ()),
    ))


def package_inputs(
    files: Sequence[File], workspace: Workspace
) -> FrozenOrderedDict[str, str]:
    packages = workspace.packages
    counted = FrozenList(
        file
        for file in files
        if file.path != LOCKFILE or workspace.locks is None
    )
    owners = FrozenList(owned(file.path, packages) for file in counted)
    grouped = FrozenOrderedDict(
        (
            name,
            FrozenList(
                file
                for file, owner in zip(counted, owners, strict=True)
                if owner == name
            ),
        )
        for name in ("", *(package.name for package in packages))
    )
    root = workspace.manifests.get(MANIFEST)
    common = common_inputs(grouped[""], root)
    return FrozenOrderedDict(
        (
            package.name,
            digest((
                common,
                *own_inputs(package, root or EMPTY, grouped, workspace),
            )),
        )
        for package in packages
    )


def own_inputs(
    package: Package,
    root: Mapping[str, object],
    grouped: Mapping[str, Sequence[File]],
    workspace: Workspace,
) -> FrozenList[str]:
    packages = workspace.packages
    closure = dependencies(FrozenOrderedSet((package.name,)), packages)
    others = FrozenList(
        other
        for other in packages
        if other.name in closure and other.name != package.name
    )
    manifest = workspace.manifests.get(manifest_of(package), EMPTY)
    locks = workspace.locks or FrozenOrderedDict[str, Sequence[str]]()
    return FrozenList((
        fingerprint(grouped[package.name]),
        digest(
            FrozenList(
                seen(file, other, workspace)
                for other in others
                for file in grouped[other.name]
            )
        ),
        *manifests.inherited(manifest, root, dev=True),
        *manifests.linted(manifest, root),
        *(
            line
            for other in others
            for line in manifests.inherited(
                workspace.manifests.get(manifest_of(other), EMPTY),
                root,
                dev=False,
            )
        ),
        *locks.get(package.name, ()),
    ))


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


def described(arguments: Sequence[str], inputs: Inputs) -> FrozenList[Package]:
    metadata = options(arguments, "--metadata=")
    if not metadata:
        return FrozenList()
    return workspace(parse_json(inputs.texts.get(metadata[0])))


def manifest_paths(packages: Sequence[Package]) -> FrozenOrderedSet[str]:
    if not packages:
        return FrozenOrderedSet()
    return FrozenOrderedSet((MANIFEST, *map(manifest_of, packages)))


def parsed_manifests(
    packages: Sequence[Package], inputs: Inputs
) -> FrozenOrderedDict[str, Mapping[str, object]]:
    found = FrozenOrderedDict(
        (path, manifests.parsed(inputs.texts.get(path)))
        for path in manifest_paths(packages)
    )
    if any(manifest is None for manifest in found.values()):
        return FrozenOrderedDict()
    return FrozenOrderedDict(
        (path, manifest)
        for path, manifest in found.items()
        if manifest is not None
    )


def resolved(
    arguments: Sequence[str], inputs: Inputs
) -> Mapping[str, Sequence[str]] | None:
    paths = options(arguments, "--resolve=")
    if not paths:
        return None
    return manifests.locked(parse_json(inputs.texts.get(paths[0])))


def request(arguments: Sequence[str], inputs: Inputs) -> Request:
    return Request(
        FrozenList((
            operands(arguments)[2],
            suites.SUITES,
            *options(arguments, "--metadata="),
            *options(arguments, "--resolve="),
            *manifest_paths(described(arguments, inputs)),
        ))
    )


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    language, tier, listed = operands(arguments)
    context = Context(
        language,
        "".join(options(arguments, "--standards=")),
        "".join(options(arguments, "--toolchain=")),
        FrozenOrderedDict(
            (name, version)
            for name, _, version in (
                tool.partition("=") for tool in options(arguments, "--tool=")
            )
        ),
    )
    files = listing(inputs.texts.get(listed, ""))
    packages = described(arguments, inputs)
    whole = fingerprint(files)
    scoped = package_inputs(
        files,
        Workspace(
            packages,
            parsed_manifests(packages, inputs),
            resolved(arguments, inputs),
        ),
    )
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
