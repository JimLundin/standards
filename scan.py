"""Report-only scan of the projects in AGENTS.md against the standards.

Usage:  python standards/scan.py [project ...]

Each project is judged by the standard configs in this folder, not by its
own configuration, so the report shows what adopting the standards would
surface. Nothing in the projects is modified: reports and build output go
to the system temp folder. Tools are fetched on demand with uvx and npx.
Rust tools run with a local cargo, or through WSL when cargo is only
installed there.
"""
# A standalone script, not part of a package:
# ruff: file-ignore[implicit-namespace-package]

from __future__ import annotations

import collections
import json
import operator
import os
import re
import shlex
import shutil

# Running the tools is the point of this script.
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
import tomllib
from pathlib import Path

STANDARDS = Path(__file__).resolve().parent
HOME = STANDARDS.parent
WORK = Path(tempfile.gettempdir()) / "standards-scan"

SOURCE = {
    ".py": "Python",
    ".pyw": "Python",
    ".rs": "Rust",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".jsx": "JavaScript",
    ".css": "CSS",
}
PYTHON = {".py", ".pyw"}
SCRIPT = {".ts", ".tsx", ".js", ".mjs", ".jsx"}
WEB = (".ts", ".tsx", ".js", ".mjs", ".jsx", ".css", ".json")
NOT_LINTED = ("package-lock.json", "tsconfig.json")
# Copied code kept for reference, not part of the project.
SNAPSHOTS = ("docs/reviews/",)
LEVELS = {"allow": "-A", "warn": "-W", "deny": "-D", "forbid": "-F"}
NODE = "node@26"  # latest stable release line
TOP = 12

type Counter = collections.Counter[str]


def out(line: str = "") -> None:
    """Write one line of the report."""
    sys.stdout.write(line + "\n")


def projects() -> list[str]:
    """List the project paths in the AGENTS.md table.

    Returns:
        Paths relative to the home folder.

    """
    text = (HOME / "AGENTS.md").read_text(encoding="utf-8")
    return re.findall(r"^\| `([^`]+)` \|", text, flags=re.MULTILINE)


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    """Run a tool and capture its output, whatever its exit status.

    Returns:
        The tool's standard output, or "" when it is not installed.

    """
    exe = shutil.which(cmd[0])
    if exe is None:
        return ""
    # Fixed tool commands, never through a shell.
    done = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [exe, *cmd[1:]],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return done.stdout


def tracked(repo: Path) -> list[str]:
    """List the repository's tracked files, without reference snapshots.

    Returns:
        Paths relative to the repository root.

    """
    files = run(["git", "ls-files"], repo).splitlines()
    return [f for f in files if not f.startswith(SNAPSHOTS)]


def is_test(path: str) -> bool:
    """Tell whether a path belongs to tests or test fixtures.

    Returns:
        True for files under a test folder or named like a test.

    """
    name = path.rsplit("/", 1)[-1]
    return (
        "tests/" in path
        or "test/" in path
        or name.startswith("test_")
        or ".test." in name
    )


def counted(counter: Counter, title: str) -> None:
    """Report a total and the most common findings."""
    out(f"- **{title}:** {sum(counter.values())} finding(s)")
    for key, n in counter.most_common(TOP):
        out(f"  - {n:5} `{key}`")


# -- volume --------------------------------------------------------------------


def volume(repo: Path, files: list[str]) -> None:
    """Report non-blank lines of source code per language."""
    lines: Counter = collections.Counter()
    count: Counter = collections.Counter()
    for f in files:
        language = SOURCE.get(Path(f).suffix)
        if language is None:
            continue
        text = (repo / f).read_text(encoding="utf-8", errors="replace")
        lines[language] += sum(1 for line in text.splitlines() if line.strip())
        count[language] += 1
    summary = ", ".join(
        f"{lang} {n:,} lines in {count[lang]} files"
        for lang, n in lines.most_common()
    )
    out(f"- **Volume (non-blank lines):** {summary or 'no source files'}")


# -- python --------------------------------------------------------------------


def python_target(repo: Path) -> str | None:
    """Find the Ruff target version from the project's requires-python.

    Returns:
        A version such as "py315", or None when the project declares none.

    """
    pyproject = repo / "pyproject.toml"
    if not pyproject.exists():
        return None
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    spec = config.get("project", {}).get("requires-python", "")
    match = re.search(r"(\d+)\.(\d+)", spec)
    return f"py{match[1]}{match[2]}" if match else None


def rule_of(finding: dict[str, str]) -> str:
    """Name a Ruff finding by its code and rule name.

    Returns:
        For example "E501 line-too-long".

    """
    name = (finding.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
    return f"{finding['code']} {name}"


def python(repo: Path, files: list[str]) -> None:
    """Report Ruff and vulture findings."""
    config = str(STANDARDS / "python" / "pyproject.toml")
    cmd = ["uvx", "-q", "ruff@latest", "check", "--config", config]
    cmd += ["--output-format", "json", "--no-cache", "--exit-zero"]
    if target := python_target(repo):
        cmd += ["--config", f"target-version='{target}'"]
    findings = json.loads(run([*cmd, "."], repo) or "[]")
    rules = collections.Counter(rule_of(f) for f in findings)
    counted(rules, "Ruff (ALL + preview)")

    sources = [f for f in files if Path(f).suffix in PYTHON]
    unused = run(["uvx", "-q", "vulture", *sources], repo).splitlines()
    out(
        f"- **Vulture (unused code, any confidence):** {len(unused)} finding(s)"
    )
    for line in unused[:TOP]:
        out(f"  - `{line}`")


# -- typescript / javascript ---------------------------------------------------


def web(repo: Path, files: list[str]) -> None:
    """Report Biome and knip findings."""
    sources = [
        f for f in files if f.endswith(WEB) and not f.endswith(NOT_LINTED)
    ]
    config = STANDARDS / "typescript" / "biome.json"
    cmd = ["npx", "-y", "@biomejs/biome@latest", "lint"]
    cmd += [f"--config-path={config}", "--reporter=json"]
    cmd += ["--max-diagnostics=none", *sources]
    diagnostics = json.loads(run(cmd, repo) or "{}").get("diagnostics", [])
    rules = collections.Counter(
        f"{d.get('severity')} {d.get('category')}" for d in diagnostics
    )
    counted(rules, "Biome (all + nursery)")

    if "package.json" not in files:
        return
    cmd = ["npx", "-y", "-p", NODE, "-p", "knip@latest", "knip"]
    report = run([*cmd, "--no-progress", "--reporter", "compact"], repo)
    sections = re.findall(
        r"^((?:Unused|Unlisted|Duplicate) [^(]+)\((\d+)\)$",
        report,
        flags=re.MULTILINE,
    )
    summary = ", ".join(f"{name.strip().lower()} {n}" for name, n in sections)
    out(f"- **Knip (unused code):** {summary or 'nothing unused'}")


# -- rust ----------------------------------------------------------------------


def lint_flags() -> list[str]:
    """Translate the [lints] tables in Cargo.fragment.toml into flags.

    Returns:
        Clippy command-line flags, lint groups first.

    """
    fragment = STANDARDS / "rust" / "Cargo.fragment.toml"
    lints = tomllib.loads(fragment.read_text(encoding="utf-8"))["lints"]
    ordered: list[tuple[int, str, str]] = []
    for tool, table in lints.items():
        for name, value in table.items():
            if isinstance(value, str):
                level, priority = value, 0
            else:
                level, priority = value["level"], value.get("priority", 0)
            lint = name if tool == "rust" else f"{tool}::{name}"
            ordered.append((priority, LEVELS[level], lint))
    ordered.sort(key=operator.itemgetter(0))
    return [part for _, flag, lint in ordered for part in (flag, lint)]


def crates(files: list[str]) -> list[str]:
    """Find top-level crates, skipping nested crates and test fixtures.

    Returns:
        Crate directories relative to the repository root.

    """
    manifests = [
        f
        for f in files
        if f.endswith("Cargo.toml") and not is_test(f) and "/fuzz/" not in f
    ]
    dirs = sorted(Path(m).parent.as_posix() for m in manifests)
    return [
        d
        for d in dirs
        if not any(d != o and (o == "." or d.startswith(o + "/")) for o in dirs)
    ]


def wsl_path(path: Path) -> str:
    """Translate a Windows path to its WSL mount path.

    Returns:
        A path under /mnt, or the POSIX form of a path with no drive.

    """
    if not path.drive:
        return path.as_posix()
    rest = path.as_posix().removeprefix(path.drive)
    return f"/mnt/{path.drive[0].lower()}{rest}"


def clippy_codes(messages: str) -> Counter:
    """Count compiler and Clippy diagnostics by level and lint.

    Returns:
        Counts keyed by "level lint".

    """
    codes: Counter = collections.Counter()
    for line in messages.splitlines():
        if not line.startswith("{"):
            continue
        message = json.loads(line)
        diagnostic = message.get("message", {})
        if message.get("reason") == "compiler-message" and diagnostic.get(
            "code"
        ):
            codes[f"{diagnostic['level']} {diagnostic['code']['code']}"] += 1
    return codes


def rust(repo: Path, files: list[str]) -> None:
    """Report Clippy and cargo-machete findings for each crate."""
    for crate in crates(files):
        name = f"{repo.name}-{crate.replace('/', '-')}".strip("-.")
        clippy = ["cargo", "+nightly", "clippy", "--all-targets", "-q"]
        clippy += ["--message-format", "json", "--", *lint_flags()]
        machete = ["cargo", "machete"]
        if shutil.which("cargo"):
            env = {
                **os.environ,
                "CARGO_TARGET_DIR": str(WORK / "target" / name),
            }
            messages = run(clippy, repo / crate, env)
            unused = run(machete, repo / crate)
        elif shutil.which("wsl"):
            messages, unused = through_wsl(repo / crate, name, clippy, machete)
        else:
            out(f"- **Clippy ({crate}):** skipped, no cargo found")
            continue
        counted(clippy_codes(messages), f"Clippy, all groups ({crate})")
        last = (unused.strip().splitlines() or ["not installed"])[-1]
        verdict = "none" if "didn't find any unused" in unused else last
        out(f"  - cargo-machete unused dependencies: {verdict}")


def through_wsl(
    crate: Path, name: str, clippy: list[str], machete: list[str]
) -> tuple[str, str]:
    """Run Clippy and cargo-machete inside WSL.

    Returns:
        Clippy's JSON messages and cargo-machete's output.

    """
    WORK.mkdir(parents=True, exist_ok=True)
    script = WORK / f"{name}.sh"
    lines = [
        'export PATH="$HOME/.cargo/bin:$PATH"',
        f"cd {shlex.quote(wsl_path(crate))}",
        f'export CARGO_TARGET_DIR="$HOME/.cache/standards-scan/{name}"',
        f"{shlex.join(clippy)} 2>/dev/null",
        "echo '=====MACHETE====='",
        f"{shlex.join(machete)} 2>&1",
    ]
    script.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    result = run(["wsl", "--", "bash", wsl_path(script)], crate)
    messages, _, unused = result.partition("=====MACHETE=====")
    return messages, unused


# -- duplication ---------------------------------------------------------------


def duplication(repo: Path) -> None:
    """Report duplicated code found by jscpd."""
    output = WORK / "jscpd" / repo.name
    shutil.rmtree(output, ignore_errors=True)
    cmd = [
        "npx",
        "-y",
        "jscpd@latest",
        "--config",
        str(STANDARDS / "jscpd.json"),
    ]
    run([*cmd, "--reporters", "json", "--output", str(output), "."], repo)
    report = output / "jscpd-report.json"
    if not report.exists():
        out("- **Duplication (jscpd):** no report")
        return
    data = json.loads(report.read_text(encoding="utf-8"))
    total = data["statistics"]["total"]
    out(
        f"- **Duplication (jscpd):** {total['clones']} clone(s), "
        f"{total['duplicatedLines']} of {total['lines']} lines "
        f"({total['percentage']:.1f}%)"
    )
    for clone in sorted(data["duplicates"], key=lambda c: -c["lines"])[:3]:
        first, second = clone["firstFile"], clone["secondFile"]
        out(
            f"  - {clone['lines']} lines: "
            f"`{first['name']}:{first['start']}` = "
            f"`{second['name']}:{second['start']}`"
        )


def scan(path: str) -> None:
    """Report every check that applies to one project."""
    repo = HOME / path
    out(f"\n## {path}\n")
    if not (repo / ".git").exists():
        out("- missing")
        return
    files = tracked(repo)
    suffixes = {Path(f).suffix for f in files}
    volume(repo, files)
    if suffixes & PYTHON:
        python(repo, files)
    if suffixes & SCRIPT:
        web(repo, files)
    if ".rs" in suffixes:
        rust(repo, files)
    duplication(repo)


def main() -> None:
    """Scan the projects named on the command line, or all of them."""
    sys.stdout.reconfigure(encoding="utf-8")
    out("# Standards scan")
    for path in sys.argv[1:] or projects():
        scan(path)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
