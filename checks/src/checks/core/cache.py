import hashlib
import json
lazy from collections.abc import Sequence

from ordered import FrozenList

from checks.core.values import Inputs, Outcome, Request

TIERS = FrozenList(("commit", "step", "release"))
VERSION = "1"


def key(fields: Sequence[str]) -> str:
    encoded = json.dumps([VERSION, *fields]).encode()
    return hashlib.sha256(encoded).hexdigest()


def above(tier: str) -> FrozenList[str]:
    return TIERS[TIERS.index(tier) + 1 :]


def below(tier: str) -> FrozenList[str]:
    return FrozenList(reversed(TIERS[: TIERS.index(tier)]))


def passes(
    tier: str, language: str, base: str, standards: str, tree: str
) -> FrozenList[str]:
    return FrozenList(
        key(("pass", level, language, base, standards, tree))
        for level in (tier, *above(tier))
    )


def seen(
    tier: str, language: str, standards: str, repository: str
) -> FrozenList[str]:
    return FrozenList(
        key(("seen", level, language, standards, repository))
        for level in (tier, *below(tier))
    )


def request(_arguments: Sequence[str], _inputs: Inputs) -> Request:
    return Request()


def run(arguments: Sequence[str], _inputs: Inputs) -> Outcome:
    tier, language, base, standards, tree, repository = arguments
    return Outcome(
        FrozenList((
            *(
                f"pass {item}"
                for item in passes(tier, language, base, standards, tree)
            ),
            *(
                f"seen {item}"
                for item in seen(tier, language, standards, repository)
            ),
        ))
    )
