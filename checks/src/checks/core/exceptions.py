import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.drift import (
    DRIFT,
    PROJECT_FILES,
    STANDARD_FILES,
    Snapshot,
    plugin_paths,
)
from checks.core.suppressions import is_source, suppressions, used_attributes
from checks.core.values import (
    Inputs,
    Outcome,
    Request,
    absolute,
    entries,
    lookup,
    matches,
    normalized,
    parse_json,
    posix,
    strings,
    table,
)
from checks.core.waivers import EXCEPTIONS, Issue, Waiver, kind, load, waived

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

LIBRARY_KINDS = FrozenOrderedSet(("lib", "rlib"))
LAYERS = FrozenOrderedSet(("core", "shell"))
SHELL = '`[package.metadata.standards] layer = "shell"`'
LAYER = "package.metadata.standards.layer"
USE = 'use "core" or "shell"'
CORELESS = "has binaries but no no_std library to hold the pure core"
NAMED = FrozenOrderedSet((
    "core-libraries",
    "shell-packages",
    "stryker-mutate",
    "biome-plugins",
))


def report(issues: Sequence[Issue]) -> Outcome:
    lines = FrozenList(f"{issue.path}: {issue.message}" for issue in issues)
    summary = f"Found {len(lines)} issues" if lines else "All checks passed"
    return Outcome(FrozenList((*lines, summary)), 1 if lines else 0)


def listing(lines: Sequence[str]) -> Outcome:
    return Outcome(FrozenList(line for line in lines if line))


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
        elif rule_kind != "drift" and not matched:
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


def check(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    language, standards, *files = arguments
    snapshot = snapshot_of(language, standards, files, inputs)
    waivers = load(inputs.texts.get(EXCEPTIONS))
    drifted = FrozenList(
        issue
        for issue in DRIFT[language](snapshot)
        if not waived(waivers.entries, issue.path, issue.rule)
    )
    return report((
        *waivers.problems,
        *waiver_issues(language, waivers.entries, snapshot),
        *suppressions(language, snapshot.project, waivers.entries),
        *drifted,
    ))


def waivers_of(inputs: Inputs) -> FrozenList[Waiver]:
    return load(inputs.texts.get(EXCEPTIONS)).entries


def ruff_config(_: Sequence[str], inputs: Inputs) -> Outcome:
    rules: FrozenOrderedDict[str, FrozenList[str]] = FrozenOrderedDict()
    for waiver in waivers_of(inputs):
        if kind("python", waiver.rule) == "ruff":
            known = rules.get(waiver.path, FrozenList())
            rules |= {waiver.path: FrozenList((*known, waiver.rule))}
    if not rules:
        return Outcome()
    pairs = ", ".join(
        f"{json.dumps(path)} = {json.dumps(list(names))}"
        for path, names in rules.items()
    )
    return listing((f"lint.extend-per-file-ignores = {{{pairs}}}",))


def immutability_args(_: Sequence[str], inputs: Inputs) -> Outcome:
    return listing(
        FrozenList(
            f"--skip={waiver.rule}:{waiver.path}"
            for waiver in waivers_of(inputs)
            if kind("python", waiver.rule) == "immutability"
        )
    )


def purity_args(_: Sequence[str], inputs: Inputs) -> Outcome:
    pairs = [
        [waiver.rule, waiver.path]
        for waiver in waivers_of(inputs)
        if kind("python", waiver.rule) == "purity"
    ]
    return listing((f"--skips={json.dumps(pairs)}",) if pairs else ())


def without(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    rule, *files = arguments
    waivers = waivers_of(inputs)
    return listing(
        FrozenList(file for file in files if not waived(waivers, file, rule))
    )


def globs_of(rule: str, waivers: Sequence[Waiver]) -> FrozenList[str]:
    return FrozenList(waiver.path for waiver in waivers if waiver.rule == rule)


def globs(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    return listing(globs_of(arguments[0], waivers_of(inputs)))


def biome_skips(file: str, waivers: Sequence[Waiver]) -> FrozenList[str]:
    return FrozenList(
        sorted(
            waiver.rule.removeprefix("lint/")
            for waiver in waivers
            if waiver.rule.startswith("lint/")
            and not waiver.rule.startswith("lint/plugin/")
            and waiver.covers(file, waiver.rule)
        )
    )


def biome_groups(files: Sequence[str], inputs: Inputs) -> Outcome:
    waivers = waivers_of(inputs)
    groups: FrozenOrderedDict[FrozenList[str], FrozenList[str]] = (
        FrozenOrderedDict()
    )
    for file in files:
        skips = biome_skips(file, waivers)
        known = groups.get(skips, FrozenList())
        groups |= {skips: FrozenList((*known, file))}
    return listing(
        FrozenList(
            "|".join((" ".join(skips), *members))
            for skips, members in groups.items()
        )
    )


def biome_plugins(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    folder = PurePosixPath(absolute(arguments[0], inputs.cwd)).parent
    return listing(
        FrozenList(
            f"{PurePosixPath(plugin).stem}|{normalized(f'{folder}/{plugin}')}"
            for plugin in plugin_paths(
                parse_json(inputs.texts.get(arguments[0]))
            )
        )
    )


def module_files(module: str) -> FrozenList[str]:
    base = module.replace(".", "/")
    return FrozenList(
        f"{root}{base}{suffix}"
        for root in ("src/", "")
        for suffix in (".py", "/__init__.py")
    )


def filter_mutmut(_: Sequence[str], inputs: Inputs) -> Outcome:
    waivers = waivers_of(inputs)
    return listing(
        FrozenList(
            line
            for line in inputs.stdin.splitlines()
            if not any(
                waived(waivers, file, "mutation")
                for file in module_files(line.strip().rsplit(".", 1)[0])
            )
        )
    )


def stryker_mutate(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    config = parse_json(inputs.texts.get(arguments[0]))
    return listing((
        ",".join((
            *strings(config.get("mutate")),
            *(f"!{glob}" for glob in globs_of("mutation", waivers_of(inputs))),
        )),
    ))


def target_kinds(package: Mapping[str, object]) -> FrozenOrderedSet[str]:
    return FrozenOrderedSet(
        kind
        for target in entries(package.get("targets"))
        for kind in strings(table(target).get("kind"))
    )


def manifest(root: str, package: Mapping[str, object]) -> str:
    path = PurePosixPath(posix(str(package.get("manifest_path"))))
    return path.relative_to(posix(root)).as_posix()


def layer(package: Mapping[str, object]) -> object:
    declared = lookup(package, "metadata.standards.layer")
    return "core" if declared is None else declared


def valid(declared: object) -> bool:
    return isinstance(declared, str) and declared in LAYERS


def is_shell(package: Mapping[str, object]) -> bool:
    return layer(package) == "shell"


def packages_of(
    metadata: Mapping[str, object],
) -> FrozenList[Mapping[str, object]]:
    return FrozenList(table(item) for item in entries(metadata.get("packages")))


def layer_issues(
    root: str, packages: Sequence[Mapping[str, object]]
) -> FrozenList[str]:
    return FrozenList(
        f"{manifest(root, package)}: {LAYER} is {json.dumps(layer(package))}; {USE}"
        for package in packages
        if not valid(layer(package))
    )


def core_libraries(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    metadata = parse_json(inputs.texts.get(arguments[0]))
    root = str(metadata.get("workspace_root"))
    packages = packages_of(metadata)
    libraries = FrozenList(
        str(package.get("name"))
        for package in packages
        if target_kinds(package) & LIBRARY_KINDS and not is_shell(package)
    )
    coreless = FrozenList(
        f"{manifest(root, package)}: {CORELESS}"
        for package in packages
        if not libraries
        and "bin" in target_kinds(package)
        and not is_shell(package)
    )
    issues = (*layer_issues(root, packages), *coreless)
    if issues:
        return Outcome(FrozenList(issues), 1)
    return listing(libraries)


def shell_packages(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    metadata = parse_json(inputs.texts.get(arguments[0]))
    return listing(
        FrozenList(
            str(package.get("id"))
            for package in packages_of(metadata)
            if is_shell(package)
        )
    )


COMMANDS = FrozenOrderedDict({
    "check": check,
    "core-libraries": core_libraries,
    "shell-packages": shell_packages,
    "ruff-config": ruff_config,
    "immutability-args": immutability_args,
    "purity-args": purity_args,
    "without": without,
    "globs": globs,
    "biome-groups": biome_groups,
    "biome-plugins": biome_plugins,
    "filter-mutmut": filter_mutmut,
    "stryker-mutate": stryker_mutate,
})


def request(arguments: Sequence[str], _inputs: Inputs) -> Request:
    command, *rest = arguments
    if command == "check":
        language, standards, *files = rest
        shared = (f"{standards}/{path}" for path in STANDARD_FILES[language])
        return Request(FrozenList((*project_paths(language, files), *shared)))
    named = FrozenList((rest[0],)) if command in NAMED else FrozenList()
    return Request(
        FrozenList((EXCEPTIONS, *named)), stdin=command == "filter-mutmut"
    )


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    command, *rest = arguments
    return COMMANDS[command](rest, inputs)
