"""The recorded passes: notes on one ref whose annotated object name is a
unit's key, travelling with origin. Fetched notes merge by union, so two
runs that record at once keep both; a project without origin keeps its
notes local."""

import subprocess
lazy from collections.abc import Sequence

from ordered import FrozenList

from checks.core.values import Outcome

REF = "refs/notes/checks"
FETCHED = "refs/notes/origin/checks"
STRATEGY = "cat_sort_uniq"
# Notes commits carry the standards' own identity, so recording needs no
# git config, as on a CI runner.
IDENTITY = FrozenList((
    "-c",
    "user.name=standards",
    "-c",
    "user.email=checks@standards.invalid",
))
# A push that origin rejects because another run pushed first is retried
# after merging that run's notes.
ATTEMPTS = 3


def git(directory: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", directory, *IDENTITY, *arguments),
        capture_output=True,
        text=True,
        check=False,
    )


def has_origin(directory: str) -> bool:
    return git(directory, "remote", "get-url", "origin").returncode == 0


def lookup(directory: str) -> FrozenList[str]:
    """The keys with a recorded pass."""
    listed = git(directory, "notes", f"--ref={REF}", "list").stdout
    return FrozenList(line.split()[1] for line in listed.splitlines())


def record(directory: str, passes: Sequence[str]) -> FrozenList[str]:
    """Records each pass, a key then its message, and returns the keys
    recorded."""
    keys, messages = passes[::2], passes[1::2]
    return FrozenList(
        key
        for key, message in zip(keys, messages, strict=True)
        if git(
            directory, "notes", f"--ref={REF}", "add", "-f", "-m", message, key
        ).returncode
        == 0
    )


def fetch(directory: str) -> bool:
    """Merges origin's notes into the local ones; true when there is no
    origin or its notes merged."""
    refspec = f"+{REF}:{FETCHED}"
    merge = ("notes", f"--ref={REF}", "merge", "-q", "-s", STRATEGY, FETCHED)
    return not has_origin(directory) or (
        git(directory, "fetch", "-q", "origin", refspec).returncode == 0
        and git(directory, *merge).returncode == 0
    )


def push(directory: str) -> bool:
    """Pushes the local notes to origin, merging and retrying when another
    run pushed first; true when there is no origin or a push landed."""
    return not has_origin(directory) or any(
        pushed(directory) for _ in range(ATTEMPTS)
    )


def pushed(directory: str) -> bool:
    """Pushes once, merging origin's notes when the push is refused."""
    landed = git(directory, "push", "-q", "origin", REF).returncode == 0
    if not landed:
        _ = fetch(directory)
    return landed


def run(arguments: Sequence[str], directory: str) -> Outcome:
    command, *rest = arguments
    match command:
        case "lookup":
            return Outcome(lookup(directory))
        case "record":
            return Outcome(record(directory, rest))
        case "fetch":
            return Outcome(status=0 if fetch(directory) else 1)
        case "push":
            return Outcome(status=0 if push(directory) else 1)
        case _:
            return Outcome(FrozenList((f"unknown notes command {command}",)), 2)
