lazy from collections.abc import Sequence

from ordered import FrozenList

from checks.core.values import Outcome
from checks.git import git

REF = "refs/notes/checks"
FETCHED = "refs/notes/origin/checks"
UNION = "cat_sort_uniq"
PUSH_ATTEMPTS = 3


def has_origin(directory: str) -> bool:
    return git(directory, "remote", "get-url", "origin").returncode == 0


def lookup(directory: str) -> FrozenList[str]:
    listed = git(directory, "notes", f"--ref={REF}").stdout
    return FrozenList(line.split()[1] for line in listed.splitlines())


def record(directory: str, passes: Sequence[str]) -> FrozenList[str]:
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
    if not has_origin(directory):
        return True
    if git(directory, "fetch", "origin", f"+{REF}:{FETCHED}").returncode:
        return False
    merge = ("notes", f"--ref={REF}", "merge", "-q", "-s", UNION, FETCHED)
    return git(directory, *merge).returncode == 0


def push(directory: str) -> bool:
    if not has_origin(directory):
        return True
    for _ in range(PUSH_ATTEMPTS):
        if git(directory, "push", "origin", REF).returncode == 0:
            return True
        _ = fetch(directory)
    return False


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
