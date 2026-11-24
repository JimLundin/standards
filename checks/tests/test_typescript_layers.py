import json
lazy from collections.abc import Mapping

from ordered import FrozenList

from checks.core.tools import request, run
from checks.core.values import Inputs, Outcome, Request
from tests.helpers import inputs

USE = 'use "core", "shell" or "ui"'


def manifest(layer: object = None) -> str:
    declared = {} if layer is None else {"standards": {"layer": layer}}
    return json.dumps({"name": "p", **declared})


def test_layers_read_the_manifest_of_every_folder_above_a_file() -> None:
    assert request(
        ("typescript-layers", "packages/a/src/x.ts", "packages/a/b.ts", "y.ts"),
        Inputs(),
    ) == Request(
        FrozenList((
            "packages/a/src/package.json",
            "packages/a/package.json",
            "packages/package.json",
            "package.json",
        ))
    )


def test_each_file_takes_the_layer_of_its_nearest_package() -> None:
    texts = {
        "package.json": manifest(),
        "packages/io/package.json": manifest("shell"),
        "packages/io/plugins/pure/package.json": manifest("core"),
        "packages/app/package.json": manifest("ui"),
        "packages/model/package.json": manifest(),
    }
    outcome = run(
        (
            "typescript-layers",
            "scripts/build.ts",
            "packages/io/src/core/read.ts",
            "packages/io/plugins/pure/src/a.ts",
            "packages/io/plugins/b.ts",
            "packages/app/src/main.tsx",
            "packages/model/lib/deep/x.ts",
        ),
        inputs(texts),
    )
    assert outcome == Outcome(
        FrozenList((
            "core\t.\tscripts/build.ts",
            "shell\tpackages/io\tpackages/io/src/core/read.ts",
            "core\tpackages/io/plugins/pure\tpackages/io/plugins/pure/src/a.ts",
            "shell\tpackages/io\tpackages/io/plugins/b.ts",
            "ui\tpackages/app\tpackages/app/src/main.tsx",
            "core\tpackages/model\tpackages/model/lib/deep/x.ts",
        ))
    )


def test_a_file_outside_any_package_is_core() -> None:
    assert run(("typescript-layers", "a.ts"), inputs({})) == Outcome(
        FrozenList(("core\t.\ta.ts",))
    )


def test_an_unknown_layer_fails_naming_its_manifest() -> None:
    texts = {
        "a/package.json": manifest("Shell"),
        "b/package.json": manifest(["ui"]),
        "c/package.json": manifest("shell"),
    }
    outcome = run(
        ("typescript-layers", "a/x.ts", "a/y.ts", "b/x.ts", "c/x.ts"),
        inputs(texts),
    )
    assert outcome == Outcome(
        FrozenList((
            f'a/package.json: standards.layer is "Shell"; {USE}',
            f'b/package.json: standards.layer is ["ui"]; {USE}',
        )),
        1,
    )


LAYER_RULES = {
    "core": {
        "includes": ["!**/*.test.ts"],
        "linter": {"rules": {"style": {"noVar": "error"}}},
    }
}


def generated(
    texts: Mapping[str, str], *files: str, cwd: str = "/work"
) -> Outcome:
    return run(
        (
            "biome-layers",
            "conf/biome.json",
            "/std/biome-layers.json",
            "out/biome.json",
            *files,
        ),
        inputs(
            {"/std/biome-layers.json": json.dumps(LAYER_RULES), **texts},
            cwd=cwd,
        ),
    )


def test_biome_layers_read_the_configs_and_the_manifests() -> None:
    assert request(
        ("biome-layers", "b.json", "l.json", "out.json", "p/x.ts"), Inputs()
    ) == Request(
        FrozenList(("b.json", "l.json", "p/package.json", "package.json"))
    )


def test_biome_layers_add_each_packages_layer_rules_as_an_override() -> None:
    base = {
        "plugins": ["./p/a.grit", "/abs/b.grit"],
        "extends": ["./shared.json", "@org/biome"],
        "overrides": [{"includes": ["**/*.test.ts"]}],
    }
    texts = {
        "conf/biome.json": json.dumps(base),
        "package.json": manifest(),
        "packages/io/package.json": manifest("shell"),
        "packages/io/pure/package.json": manifest(),
    }
    outcome = generated(
        texts,
        "x.ts",
        "packages/io/a.ts",
        "packages/io/pure/b.ts",
        "packages/io/pure/c.ts",
    )
    core = LAYER_RULES["core"]
    assert outcome.lines == ()
    assert outcome.status == 0
    assert json.loads(outcome.writes["out/biome.json"]) == {
        "plugins": ["/work/conf/p/a.grit", "/abs/b.grit"],
        "extends": ["/work/conf/shared.json", "@org/biome"],
        "overrides": [
            {"includes": ["**/*.test.ts"]},
            {
                **core,
                "includes": [
                    "**",
                    "!packages/io/**",
                    "!packages/io/pure/**",
                    "!**/*.test.ts",
                ],
            },
            {**core, "includes": ["packages/io/pure/**", "!**/*.test.ts"]},
        ],
    }


def test_biome_layers_write_nothing_on_an_unknown_layer() -> None:
    texts = {"conf/biome.json": "{}", "package.json": manifest("domain")}
    assert generated(texts, "x.ts") == Outcome(
        FrozenList((f'package.json: standards.layer is "domain"; {USE}',)), 1
    )


def test_biome_layers_fail_on_a_config_that_is_not_json() -> None:
    texts = {"conf/biome.json": "{ // a comment\n}"}
    assert generated(texts, "x.ts") == Outcome(
        FrozenList(("conf/biome.json: not a JSON object",)), 1
    )
