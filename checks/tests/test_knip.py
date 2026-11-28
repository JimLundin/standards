import json
lazy from collections.abc import Mapping

from ordered import FrozenList

from checks.core.tools import request, run
from checks.core.values import Inputs, Request, parse_json
from tests.helpers import inputs

WRITTEN = "node_modules/.cache/standards/knip.json"
NEGATED = (
    "!**/test/**!",
    "!**/tests/**!",
    "!**/__tests__/**!",
    "!**/*.test.*!",
    "!**/*.spec.*!",
)
DEFAULT = "**/*.{js,mjs,cjs,jsx,ts,tsx,mts,cts}!"


def production(texts: Mapping[str, str]) -> Mapping[str, object]:
    outcome = run(("knip-config",), inputs(texts))
    assert outcome.lines == (WRITTEN,)
    return parse_json(outcome.writes[WRITTEN])


def test_knip_config_reads_the_project_s_knip_config_and_package_json() -> None:
    assert request(("knip-config",), Inputs()) == Request(
        FrozenList(("knip.json", "knip.jsonc", "package.json"))
    )


def test_every_workspace_leaves_the_test_files_out_of_production() -> None:
    texts = {"package.json": json.dumps({"workspaces": ["./packages/*"]})}
    assert production(texts) == {
        "workspaces": {
            ".": {"project": [DEFAULT, *NEGATED]},
            "packages/*": {"project": [DEFAULT, *NEGATED]},
        }
    }


def test_the_project_s_own_patterns_keep_their_place_before_the_negations() -> (
    None
):
    config = {
        "$schema": "s",
        "ignore": ["gen/**"],
        "entry": "src/main.ts!",
        "project": ["src/**/*.ts!"],
    }
    assert production({"knip.jsonc": json.dumps(config)}) == {
        **config,
        "workspaces": {
            ".": {
                "ignore": ["gen/**"],
                "entry": ["src/main.ts!", *NEGATED],
                "project": ["src/**/*.ts!", *NEGATED],
            }
        },
    }


def test_a_configured_workspace_keeps_its_config_beside_the_listed_ones() -> (
    None
):
    config = {"workspaces": {"packages/core": {"project": ["lib/**!"]}}}
    manifest = {"workspaces": {"packages": ["packages/*", "!packages/skip"]}}
    texts = {
        "knip.json": json.dumps(config),
        "package.json": json.dumps(manifest),
    }
    assert production(texts) == {
        "workspaces": {
            ".": {"project": [DEFAULT, *NEGATED]},
            "packages/*": {"project": [DEFAULT, *NEGATED]},
            "packages/core": {"project": ["lib/**!", *NEGATED]},
        }
    }
