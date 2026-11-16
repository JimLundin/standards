import sys
from dataclasses import replace
from pathlib import Path

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.tools import request, run
from checks.core.values import Inputs


def read(paths: FrozenList[str]) -> FrozenOrderedDict[str, str]:
    return FrozenOrderedDict(
        (path, Path(path).read_bytes().decode().replace("\r\n", "\n"))
        for path in paths
        if Path(path).is_file()
    )


def collect(
    arguments: FrozenList[str], inputs: Inputs, attempted: FrozenOrderedSet[str]
) -> Inputs:
    fresh = FrozenList(
        path
        for path in request(arguments, inputs).paths
        if path not in attempted
    )
    if not fresh:
        return inputs
    gathered = Inputs(inputs.texts | read(fresh), cwd=inputs.cwd)
    return collect(arguments, gathered, attempted | FrozenOrderedSet(fresh))


def gather(arguments: FrozenList[str]) -> Inputs:
    inputs = collect(
        arguments, Inputs(cwd=str(Path.cwd())), FrozenOrderedSet[str]()
    )
    if request(arguments, inputs).stdin:
        return replace(inputs, stdin=sys.stdin.read())
    return inputs


def main() -> int:
    arguments = FrozenList(sys.argv[1:])
    outcome = run(arguments, gather(arguments))
    for path, text in outcome.writes.items():
        _ = Path(path).write_bytes(text.encode())
    _ = sys.stdout.buffer.write(
        "".join(f"{line}\n" for line in outcome.lines).encode()
    )
    return outcome.status
