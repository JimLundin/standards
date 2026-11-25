import json
lazy from collections.abc import Mapping

from ordered import FrozenList, FrozenOrderedDict

from checks.core.decoding import decode
from checks.core.tools import request, run
from checks.core.values import Inputs, Outcome, Request, entries, strings, table
from tests.helpers import entry, inputs

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


def named(name: str, layer: object = None) -> str:
    declared = {} if layer is None else {"standards": {"layer": layer}}
    return json.dumps({"name": name, **declared})


def overrides(texts: Mapping[str, str], *files: str) -> FrozenList[object]:
    outcome = run(
        ("oxlint-config", "/std/oxlint.config.ts", *files),
        inputs(texts, cwd="/work"),
    )
    (config,) = outcome.writes.values()
    return FrozenList(
        decode(line.strip().removesuffix(","))
        for line in config.splitlines()
        if '"no-restricted-imports"' in line
    )


def restriction(override: object) -> Mapping[str, object]:
    rules = table(table(override).get("rules"))
    level, options = entries(rules.get("no-restricted-imports"))
    assert level == "error"
    return table(options)


def group(override: object) -> FrozenList[str]:
    (pattern,) = entries(restriction(override).get("patterns"))
    return strings(table(pattern).get("group"))


def scope(override: object) -> tuple[FrozenList[str], FrozenList[str]]:
    return (
        strings(table(override).get("files")),
        strings(table(override).get("excludeFiles")),
    )


TOOLING = (
    "/work/**/*.test.{ts,tsx}",
    "/work/**/test/**",
    "/work/**/*.config.{ts,tsx,mts,js,mjs}",
    "/work/**/vitest.setup.ts",
)
NESTED = FrozenOrderedDict({
    "package.json": named("root"),
    "packages/io/package.json": named("@w/io", "shell"),
    "packages/io/pure/package.json": named("@w/pure"),
    "packages/app/package.json": named("@w/app", "ui"),
})
NESTED_FILES = (
    "x.ts",
    "packages/io/a.ts",
    "packages/io/pure/b.ts",
    "packages/app/c.tsx",
)


def test_oxlint_config_reads_the_manifests_of_the_files_it_lints() -> None:
    assert request(
        ("oxlint-config", "/std/oxlint.config.ts", "p/x.ts"), Inputs()
    ) == Request(
        FrozenList(("exceptions.toml", "p/package.json", "package.json"))
    )


def test_each_package_restricts_imports_in_its_files_alone() -> None:
    scopes = FrozenList(map(scope, overrides(NESTED, *NESTED_FILES)))
    assert scopes == (
        (
            ("/work/**",),
            (
                "/work/packages/io/**",
                "/work/packages/io/pure/**",
                "/work/packages/app/**",
                *TOOLING,
            ),
        ),
        (("/work/packages/io/**",), ("/work/packages/io/pure/**", *TOOLING)),
        (("/work/packages/io/pure/**",), TOOLING),
        (("/work/packages/app/**",), TOOLING),
    )


def test_the_shell_and_the_ui_may_not_import_each_other() -> None:
    _, shell, _, ui = overrides(NESTED, *NESTED_FILES)
    assert group(shell) == ("@w/app", "@w/app/**")
    assert group(ui) == ("@w/io", "@w/io/**")


EFFECT_HOOKS = FrozenOrderedDict({
    "name": "react",
    "importNames": ["useEffect", "useLayoutEffect"],
    "message": (
        "an effect in a component: run it in an atom of effect/reactivity"
    ),
})


def test_the_ui_may_not_import_reacts_effect_hooks() -> None:
    *_, ui = overrides(NESTED, *NESTED_FILES)
    assert restriction(ui).get("paths") == [EFFECT_HOOKS]
    alone = {"packages/app/package.json": named("@w/app", "ui")}
    (_, only) = overrides(alone, "x.ts", "packages/app/c.tsx")
    assert restriction(only) == {"paths": [EFFECT_HOOKS]}


def test_only_a_ui_package_restricts_browser_globals() -> None:
    outcome = run(
        ("oxlint-config", "/std/oxlint.config.ts", *NESTED_FILES),
        inputs(NESTED, cwd="/work"),
    )
    (config,) = outcome.writes.values()
    (browser,) = (
        line for line in config.splitlines() if "no-restricted-globals" in line
    )
    scoped = (
        '\t\t{"files": ["/work/packages/app/**"], "excludeFiles": ['
        '"/work/**/*.test.{ts,tsx}"'
    )
    assert browser.startswith(scoped)
    assert '"no-restricted-globals": ["error", ...restricted(' in browser
    assert '"no-restricted-properties": ["error", ...restricted(' in browser


CORE_GROUP = (
    "**",
    "!./**",
    "!#*",
    "!#*/**",
    "!../**",
    "!root",
    "!root/**",
    "**/*/root",
    "!@w/pure",
    "!@w/pure/**",
    "!effect",
    "**/*/effect",
    "!effect/Function",
    "!effect/HashMap",
    "!effect/HashSet",
    "!effect/http-api",
    "!effect/rpc",
    "!effect/Array",
    "!effect/Data",
    "!effect/Equal",
    "!effect/Hash",
    "!effect/Match",
    "!effect/Number",
    "!effect/Option",
    "!effect/Order",
    "!effect/Record",
    "!effect/Result",
    "!effect/Schema",
    "!effect/String",
    "!effect/Struct",
    "!effect/http-api/HttpApi",
    "!effect/http-api/HttpApiEndpoint",
    "!effect/http-api/HttpApiError",
    "!effect/http-api/HttpApiGroup",
    "!effect/http-api/HttpApiMiddleware",
    "!effect/http-api/HttpApiSchema",
    "!effect/http-api/HttpApiSecurity",
    "!effect/rpc/Rpc",
    "!effect/rpc/RpcGroup",
    "!effect/rpc/RpcMiddleware",
    "!effect/rpc/RpcSchema",
)


def paths(override: object) -> FrozenList[Mapping[str, object]]:
    return FrozenList(map(table, entries(restriction(override).get("paths"))))


def allowed(override: object) -> FrozenOrderedDict[str, object]:
    return FrozenOrderedDict(
        (str(path.get("name")), path.get("allowImportNames"))
        for path in paths(override)
    )


def test_the_core_imports_core_packages_and_effects_pure_modules() -> None:
    root, _, pure, _ = overrides(NESTED, *NESTED_FILES)
    assert group(root) == CORE_GROUP
    assert group(pure) == CORE_GROUP
    assert allowed(root) == {
        "effect": [
            "Array",
            "Data",
            "Equal",
            "Hash",
            "Match",
            "Number",
            "Option",
            "Order",
            "Record",
            "Result",
            "Schema",
            "String",
            "Struct",
            "flow",
            "pipe",
        ],
        "effect/Function": ["flow", "pipe"],
        "effect/http-api": [
            "HttpApi",
            "HttpApiEndpoint",
            "HttpApiError",
            "HttpApiGroup",
            "HttpApiMiddleware",
            "HttpApiSchema",
            "HttpApiSecurity",
        ],
        "effect/rpc": ["Rpc", "RpcGroup", "RpcMiddleware", "RpcSchema"],
        "effect/HashMap": None,
        "effect/HashSet": None,
    }


def test_the_core_imports_its_own_packages_subpath_imports() -> None:
    root, _, pure, _ = overrides(NESTED, *NESTED_FILES)
    for override in (root, pure):
        assert {"!#*", "!#*/**"} <= set(group(override))


def test_a_purity_exception_allows_its_module_in_its_core_files() -> None:
    texts = {
        **NESTED,
        "exceptions.toml": entry("x.ts", "purity:lodash")
        + entry("x.ts", "purity:effect/http-api")
        + entry("*.ts", "purity:@w/io")
        + entry("packages/io/a.ts", "purity:other"),
    }
    *layers, excepted, wider = overrides(
        texts, *NESTED_FILES, "y.ts", "packages/app/d.ts"
    )
    assert len(layers) == len(NESTED)
    assert scope(wider) == (("/work/y.ts",), TOOLING)
    assert group(wider)[-2:] == ("!@w/io", "!@w/io/**")
    assert scope(excepted) == (("/work/x.ts",), TOOLING)
    assert group(excepted)[-7:] == (
        "!lodash",
        "!lodash/**",
        "**/*/lodash",
        "!effect/http-api",
        "!effect/http-api/**",
        "!@w/io",
        "!@w/io/**",
    )
    assert "effect/http-api" not in allowed(excepted)
    assert "effect" in allowed(excepted)


def test_a_purity_exception_for_effect_keeps_hash_maps_banned() -> None:
    texts = {**NESTED, "exceptions.toml": entry("x.ts", "purity:effect")}
    excepted = overrides(texts, *NESTED_FILES)[-1]
    assert allowed(excepted) == {
        "effect": None,
        "effect/HashMap": None,
        "effect/HashSet": None,
    }
    (barrel, *_) = paths(excepted)
    assert barrel.get("importNames") == ["HashMap", "HashSet"]


def test_oxlint_config_writes_nothing_on_an_unknown_layer() -> None:
    texts = {"package.json": manifest("domain")}
    assert run(
        ("oxlint-config", "/std/oxlint.config.ts", "x.ts"), inputs(texts)
    ) == Outcome(
        FrozenList((f'package.json: standards.layer is "domain"; {USE}',)), 1
    )


def test_the_map_of_code_leaves_tests_and_tool_configs_out() -> None:
    files = (
        "src/a.ts",
        "src/a.test.ts",
        "src/view.test.tsx",
        "packages/p/test/helpers.ts",
        "vitest.config.ts",
        "packages/p/vite.config.mts",
        "vitest.setup.ts",
        "src/view.tsx",
    )
    outcome = run(("typescript-layers", "--code", *files), inputs({}))
    assert outcome == Outcome(
        FrozenList(("core\t.\tsrc/a.ts", "core\t.\tsrc/view.tsx"))
    )
    assert len(run(("typescript-layers", *files), inputs({})).lines) == len(
        files
    )
