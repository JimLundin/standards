import subprocess
from pathlib import Path

import pytest
from ordered import FrozenList

from checks import notes
from checks.core.values import Outcome
from tests.helpers import assert_names_the_fix

FIRST = "1" * 40
SECOND = "2" * 40
REJECT_ONCE = """\
#!/bin/sh
[ -e "$GIT_DIR/rejected" ] && exit 0
touch "$GIT_DIR/rejected"
exit 1
"""
REJECT = "#!/bin/sh\nexit 1\n"


def git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(directory), *arguments),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture
def origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    empty = tmp_path / "gitconfig"
    _ = empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in ("NAME", "EMAIL"):
        for role in ("AUTHOR", "COMMITTER"):
            monkeypatch.delenv(f"GIT_{role}_{name}", raising=False)
    _ = git(tmp_path, "init", "-q", "--bare", "origin.git")
    return tmp_path / "origin.git"


def clone(origin: Path, name: str) -> str:
    directory = origin.parent / name
    _ = git(origin.parent, "init", "-q", name)
    _ = git(directory, "remote", "add", "origin", str(origin))
    return str(directory)


def hook(origin: Path, script: str) -> None:
    path = origin / "hooks/pre-receive"
    _ = path.write_text(script, newline="\n")
    path.chmod(0o755)


def message(directory: str | Path, key: str) -> FrozenList[str]:
    shown = git(Path(directory), "notes", f"--ref={notes.REF}", "show", key)
    return FrozenList(shown.splitlines())


def test_a_recorded_pass_is_looked_up_by_its_key(origin: Path) -> None:
    project = clone(origin, "project")
    assert notes.lookup(project) == ()
    recorded = notes.record(project, (FIRST, "python lint .", SECOND, "x"))
    assert recorded == (FIRST, SECOND)
    assert notes.lookup(project) == (FIRST, SECOND)
    assert message(project, FIRST) == ("python lint .",)


def test_recording_a_pass_again_replaces_its_message(origin: Path) -> None:
    project = clone(origin, "project")
    _ = notes.record(project, (FIRST, "python lint ."))
    assert notes.record(project, (FIRST, "python format .")) == (FIRST,)
    assert message(project, FIRST) == ("python format .",)


def test_a_key_without_its_message_is_refused(origin: Path) -> None:
    project = clone(origin, "project")
    with pytest.raises(ValueError, match="zip"):
        _ = notes.record(project, (FIRST, "python lint .", SECOND))


def test_notes_commits_carry_the_standards_identity(origin: Path) -> None:
    project = clone(origin, "project")
    _ = notes.record(project, (FIRST, "python lint ."))
    author = git(Path(project), "log", "-1", "--format=%an <%ae>", notes.REF)
    assert author.strip() == "standards <checks@standards.invalid>"


def test_a_project_without_origin_keeps_its_notes_local(origin: Path) -> None:
    _ = git(origin.parent, "init", "-q", "local")
    project = str(origin.parent / "local")
    _ = notes.record(project, (FIRST, "python lint ."))
    assert notes.fetch(project)
    assert notes.push(project)
    assert notes.lookup(project) == (FIRST,)


def test_fetching_from_an_origin_without_notes_fails(origin: Path) -> None:
    project = clone(origin, "project")
    assert not notes.fetch(project)
    assert notes.lookup(project) == ()


def test_a_pushed_pass_is_fetched_by_another_clone(origin: Path) -> None:
    first, second = clone(origin, "first"), clone(origin, "second")
    _ = notes.record(first, (FIRST, "python lint ."))
    assert notes.push(first)
    assert notes.fetch(second)
    assert notes.lookup(second) == (FIRST,)


def test_a_push_behind_origin_merges_and_retries(origin: Path) -> None:
    first, second = clone(origin, "first"), clone(origin, "second")
    _ = notes.record(first, (FIRST, "python lint ."))
    _ = notes.record(second, (SECOND, "python format ."))
    assert notes.push(first)
    assert notes.push(second)
    assert notes.lookup(str(origin)) == (FIRST, SECOND)


def test_notes_recorded_at_once_under_one_key_merge_by_union(
    origin: Path,
) -> None:
    first, second = clone(origin, "first"), clone(origin, "second")
    _ = notes.record(first, (FIRST, "rust lint a"))
    _ = notes.record(second, (FIRST, "rust lint b"))
    assert notes.push(first)
    assert notes.push(second)
    assert message(origin, FIRST) == ("rust lint a", "rust lint b")
    assert notes.fetch(first)
    assert message(first, FIRST) == ("rust lint a", "rust lint b")


def test_a_rejected_push_is_retried(origin: Path) -> None:
    hook(origin, REJECT_ONCE)
    project = clone(origin, "project")
    _ = notes.record(project, (FIRST, "python lint ."))
    assert notes.push(project)
    assert notes.lookup(str(origin)) == (FIRST,)


def test_a_push_origin_keeps_rejecting_fails(origin: Path) -> None:
    hook(origin, REJECT)
    project = clone(origin, "project")
    _ = notes.record(project, (FIRST, "python lint ."))
    assert not notes.push(project)
    assert notes.lookup(str(origin)) == ()


def test_the_command_dispatches_to_each_operation(origin: Path) -> None:
    project = clone(origin, "project")
    assert notes.run(("record", FIRST, "python lint ."), project) == Outcome(
        FrozenList((FIRST,))
    )
    assert notes.run(("lookup",), project) == Outcome(FrozenList((FIRST,)))
    assert notes.run(("push",), project) == Outcome()
    assert notes.run(("fetch",), project) == Outcome()
    unknown = notes.run(("move",), project)
    assert unknown == Outcome(
        FrozenList((
            (
                "unknown notes command move; fix: use `lookup`, `record`,"
                " `fetch` or `push`"
            ),
        )),
        2,
    )
    assert_names_the_fix(unknown.lines[0])


def test_a_failed_fetch_and_push_fail_the_command(origin: Path) -> None:
    project = clone(origin, "project")
    assert notes.run(("fetch",), project).status == 1
    hook(origin, REJECT)
    _ = notes.record(project, (FIRST, "python lint ."))
    assert notes.run(("push",), project).status == 1
