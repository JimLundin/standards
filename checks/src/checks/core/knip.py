import json
from dataclasses import dataclass
lazy from collections.abc import Mapping, Sequence

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.sides import TYPESCRIPT_EXTENSIONS, tests_of
from checks.core.values import (
    EMPTY,
    Inputs,
    Outcome,
    Request,
    parse_json,
    strings,
    table,
)

CONFIGS = FrozenList(("knip.json", "knip.jsonc"))
MANIFEST = "package.json"
WRITTEN = "node_modules/.cache/standards/knip.json"
ROOT = "."
PATTERNS = FrozenList(("entry", "project"))
ROOT_ONLY = FrozenOrderedSet((
    "$schema",
    "rules",
    "cycles",
    "ignoreWorkspaces",
    "compilers",
    "asyncCompilers",
    "tags",
    "treatConfigHintsAsErrors",
    "treatTagHintsAsErrors",
    "preprocessor",
    "preprocessorOptions",
    "include",
    "exclude",
    "workspaces",
))
DEFAULT_PROJECT = FrozenList((f"**/*.{{{','.join(TYPESCRIPT_EXTENSIONS)}}}!",))
NEGATED_TESTS = FrozenList(f"!{glob}!" for glob in tests_of("typescript"))


@dataclass(frozen=True, slots=True)
class Config:
    path: str
    fields: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Negation:
    where: str
    pattern: str
    files: str


def config_of(texts: Mapping[str, str]) -> Config:
    path = next((path for path in CONFIGS if path in texts), CONFIGS[0])
    return Config(path, parse_json(texts.get(path)))


def patterns(value: object) -> FrozenList[str]:
    if isinstance(value, str):
        return FrozenList((value,))
    return strings(value)


def scopes(
    config: Mapping[str, object],
) -> FrozenOrderedDict[str, Mapping[str, object]]:
    keyed = table(config.get("workspaces"))
    if "workspaces" in config:
        root = table(keyed.get(ROOT))
    else:
        root = FrozenOrderedDict(
            (key, value)
            for key, value in config.items()
            if key not in ROOT_ONLY
        )
    return FrozenOrderedDict({
        ROOT: root,
        **{key: table(value) for key, value in keyed.items()},
    })


def negations(config: Mapping[str, object]) -> FrozenList[Negation]:
    places = (
        ("", "", config),
        *(
            (
                f"workspaces.{key}.",
                "" if key == ROOT else f"{key}/",
                table(scope),
            )
            for key, scope in table(config.get("workspaces")).items()
        ),
    )
    return FrozenList(
        Negation(f"{where}{key}", pattern, f"{folder}{pattern.strip('!')}")
        for where, folder, scope in places
        for key in PATTERNS
        for pattern in patterns(scope.get(key))
        if pattern.startswith("!")
    )


def listed_workspaces(manifest: Mapping[str, object]) -> FrozenList[str]:
    listed = manifest.get("workspaces")
    globs = strings(listed) or strings(table(listed).get("packages"))
    return FrozenList(
        glob.removeprefix("./") for glob in globs if not glob.startswith("!")
    )


def production(scope: Mapping[str, object]) -> Mapping[str, object]:
    entry = (
        {"entry": [*patterns(scope["entry"]), *NEGATED_TESTS]}
        if "entry" in scope
        else {}
    )
    project = (
        patterns(scope["project"]) if "project" in scope else DEFAULT_PROJECT
    )
    return {**scope, **entry, "project": [*project, *NEGATED_TESTS]}


def production_config(
    config: Mapping[str, object], manifest: Mapping[str, object]
) -> Mapping[str, object]:
    configured = scopes(config)
    workspaces = FrozenOrderedDict({
        ROOT: configured[ROOT],
        **dict.fromkeys(listed_workspaces(manifest), EMPTY),
        **configured,
    })
    return {
        **config,
        "workspaces": {
            key: production(scope) for key, scope in workspaces.items()
        },
    }


def request(_: Sequence[str], _inputs: Inputs) -> Request:
    return Request(FrozenList((*CONFIGS, MANIFEST)))


def run(_: Sequence[str], inputs: Inputs) -> Outcome:
    config = production_config(
        config_of(inputs.texts).fields, parse_json(inputs.texts.get(MANIFEST))
    )
    return Outcome(
        FrozenList((WRITTEN,)),
        writes=FrozenOrderedDict({WRITTEN: json.dumps(config)}),
    )
