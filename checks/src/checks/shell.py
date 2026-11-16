import sys
from pathlib import Path

from ordered import FrozenList, FrozenOrderedDict, FrozenOrderedSet

from checks.core.tools import request, run
from checks.core.values import Inputs


def read(paths: FrozenList[str]) -> FrozenOrderedDict[str, str]:
    return FrozenOrderedDict(
        (path, Path(path).read_text(encoding="utf-8"))
        for path in paths
        if Path(path).is_file()
    )


def gather(arguments: FrozenList[str]) -> Inputs:
    inputs = Inputs(cwd=str(Path.cwd()))
    attempted = FrozenOrderedSet[str]()
    while fresh := FrozenList(
        path
        for path in request(arguments, inputs).paths
        if path not in attempted
    ):
        attempted |= FrozenOrderedSet(fresh)
        inputs = Inputs(inputs.texts | read(fresh), inputs.stdin, inputs.cwd)
    if request(arguments, inputs).stdin:
        return Inputs(inputs.texts, sys.stdin.read(), inputs.cwd)
    return inputs


def main() -> int:
    arguments = FrozenList(sys.argv[1:])
    outcome = run(arguments, gather(arguments))
    for path, text in outcome.writes.items():
        _ = Path(path).write_text(text, encoding="utf-8")
    _ = sys.stdout.buffer.write(
        "".join(f"{line}\n" for line in outcome.lines).encode()
    )
    return outcome.status
