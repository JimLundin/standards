"""Git, run with the standards' own identity, so recording needs no git
config, as on a CI runner."""

import subprocess

from ordered import FrozenList

IDENTITY = FrozenList((
    "-c",
    "user.name=standards",
    "-c",
    "user.email=checks@standards.invalid",
))


def git(directory: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", directory, *IDENTITY, *arguments),
        capture_output=True,
        text=True,
        check=False,
    )
