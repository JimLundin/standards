from typing import TYPE_CHECKING
lazy from collections.abc import Sequence

from ordered import FrozenOrderedDict

from checks.core import (
    cache,
    immutability,
    policy,
    purity,
    rust_api,
    rust_core,
    rust_layers,
    rust_shell,
    scope,
    tool_config,
)

if TYPE_CHECKING:
    from checks.core.values import Inputs, Outcome, Request

TOOLS = FrozenOrderedDict({
    "cache-keys": (cache.request, cache.run),
    "core-clippy": (rust_core.clippy_request, rust_core.clippy_run),
    "core-libraries": (rust_layers.request, rust_layers.run),
    "immutability": (immutability.request, immutability.run),
    "policy": (policy.request, policy.run),
    "purity": (purity.request, purity.run),
    "rust-api": (rust_api.request, rust_api.run),
    "rust-core": (rust_core.request, rust_core.run),
    "rust-roots": (rust_shell.roots_request, rust_shell.roots),
    "rust-shell": (rust_shell.request, rust_shell.run),
    "scope": (scope.request, scope.run),
    "tool-config": (tool_config.request, tool_config.run),
})


def request(arguments: Sequence[str], inputs: Inputs) -> Request:
    tool, *rest = arguments
    return TOOLS[tool][0](rest, inputs)


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    tool, *rest = arguments
    return TOOLS[tool][1](rest, inputs)
