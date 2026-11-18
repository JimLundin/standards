from typing import TYPE_CHECKING
lazy from collections.abc import Sequence

from ordered import FrozenOrderedDict

from checks.core import (
    cache,
    exceptions,
    immutability,
    purity,
    rust_api,
    rust_shell,
    scope,
)

if TYPE_CHECKING:
    from checks.core.values import Inputs, Outcome, Request

TOOLS = FrozenOrderedDict({
    "cache-keys": (cache.request, cache.run),
    "exceptions": (exceptions.request, exceptions.run),
    "immutability": (immutability.request, immutability.run),
    "purity": (purity.request, purity.run),
    "rust-api": (rust_api.request, rust_api.run),
    "rust-roots": (rust_shell.roots_request, rust_shell.roots),
    "rust-shell": (rust_shell.request, rust_shell.run),
    "scope": (scope.request, scope.run),
})


def request(arguments: Sequence[str], inputs: Inputs) -> Request:
    tool, *rest = arguments
    return TOOLS[tool][0](rest, inputs)


def run(arguments: Sequence[str], inputs: Inputs) -> Outcome:
    tool, *rest = arguments
    return TOOLS[tool][1](rest, inputs)
