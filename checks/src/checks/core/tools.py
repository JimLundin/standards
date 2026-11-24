from typing import TYPE_CHECKING
lazy from collections.abc import Sequence

from ordered import FrozenOrderedDict

from checks.core import (
    attribution,
    immutability,
    policy,
    purity,
    rust_api,
    rust_core,
    rust_layers,
    rust_shell,
    tool_config,
    typescript_layers,
    units,
)

if TYPE_CHECKING:
    from checks.core.values import Inputs, Outcome, Request

TOOLS = FrozenOrderedDict({
    "biome-layers": (
        typescript_layers.config_request,
        typescript_layers.config_run,
    ),
    "biome-plugins": (
        typescript_layers.plugins_request,
        typescript_layers.plugins_run,
    ),
    "core-clippy": (rust_core.clippy_request, rust_core.clippy_run),
    "core-libraries": (rust_layers.request, rust_layers.run),
    "immutability": (immutability.request, immutability.run),
    "passed": (attribution.request, attribution.run),
    "policy": (policy.request, policy.run),
    "purity": (purity.request, purity.run),
    "rust-api": (rust_api.request, rust_api.run),
    "rust-core": (rust_core.request, rust_core.run),
    "rust-roots": (rust_shell.roots_request, rust_shell.roots),
    "rust-shell": (rust_shell.request, rust_shell.run),
    "rust-shell-share": (rust_shell.request, rust_shell.share_run),
    "typescript-layers": (typescript_layers.request, typescript_layers.run),
    "units": (units.request, units.run),
    **tool_config.COMMANDS,
})


def request(arguments: Sequence[str], inputs: Inputs) -> Request:
    tool, *rest = arguments
    return TOOLS[tool][0](rest, inputs)


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    tool, *rest = arguments
    return TOOLS[tool][1](rest, inputs)
