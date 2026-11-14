"""Report-only scan of the projects in AGENTS.md against the standard tooling.

Usage:  python standards/scan.py [project ...]

Each project is judged by the standard configs in this folder, not by its own
configuration, so the report shows what adopting the standard would surface.
Nothing in the projects is modified: reports and build output go to the system
temp folder. Tools are fetched on demand with uvx and npx. Rust tools run with
a local cargo, or through WSL when cargo is only installed there.
"""

from __future__ import annotations

import collections
import json
import os
import re
import shlex
import shutil
import subprocess
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
WEB = (".ts", ".tsx", ".js", ".mjs", ".jsx", ".css", ".json")
SNAPSHOTS = ("docs/reviews/",)  # copied code kept for reference, not part of the project
LEVELS = {"allow": "-A", "warn": "-W", "deny": "-D", "forbid": "-F"}
TOP = 12


def projects() -> list[str]:
    """Project paths from the AGENTS.md table."""
    text = (HOME / "AGENTS.md").read_text(encoding="utf-8")
    return re.findall(r"^\| `([^`]+)` \|", text, flags=re.MULTILINE)


def run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    exe = shutil.which(cmd[0])
    if exe is None:
        return ""
    done = subprocess.run(
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
    out = run(["git", "ls-files"], repo).splitlines()
    return [f for f in out if not f.startswith(SNAPSHOTS)]


def is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return "tests/" in path or "test/" in path or name.startswith("test_") or ".test." in name


def counted(counter: collections.Counter[str], title: str) -> None:
    total = sum(counter.values())
    print(f"- **{title}:** {total} finding(s)")
    for key, n in counter.most_common(TOP):
        print(f"  - {n:5} `{key}`")


# -- volume -------------------------------------------------------------------


def volume(repo: Path, files: list[str]) -> None:
    lines: collections.Counter[str] = collections.Counter()
    count: collections.Counter[str] = collections.Counter()
    for f in files:
        language = SOURCE.get(Path(f).suffix)
        if language is None:
            continue
        text = (repo / f).read_text(encoding="utf-8", errors="replace")
        lines[language] += sum(1 for line in text.splitlines() if line.strip())
        count[language] += 1
    summary = ", ".join(f"{lang} {lines[lang]:,} lines in {count[lang]} files" for lang, _ in lines.most_common())
    print(f"- **Volume (non-blank lines):** {summary or 'no source files'}")


# -- python -------------------------------------------------------------------


def python_target(repo: Path) -> str | None:
    pyproject = repo / "pyproject.toml"
    if not pyproject.exists():
        return None
    spec = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("requires-python", "")
    match = re.search(r"(\d+)\.(\d+)", spec)
    return f"py{match[1]}{match[2]}" if match else None


def python(repo: Path, files: list[str]) -> None:
    cmd = [
        "uvx",
        "-q",
        "ruff@latest",
        "check",
        "--config",
        str(STANDARDS / "python" / "ruff.toml"),
        "--output-format",
        "json",
        "--no-cache",
        "--exit-zero",
    ]
    if target := python_target(repo):
        cmd += ["--config", f"target-version='{target}'"]
    findings = json.loads(run([*cmd, "."], repo) or "[]")
    counted(
        collections.Counter(f"{f['code']} {(f.get('url') or '').rstrip('/').rsplit('/', 1)[-1]}" for f in findings),
        "Ruff (standard rules)",
    )

    sources = [f for f in files if Path(f).suffix in (".py", ".pyw") and not is_test(f)]
    unused = run(["uvx", "-q", "vulture", "--min-confidence", "80", *sources], repo).splitlines()
    print(f"- **Vulture (unused code, 80% confidence):** {len(unused)} finding(s)")
    for line in unused[:TOP]:
        print(f"  - `{line}`")


# -- typescript / javascript ----------------------------------------------------


def web(repo: Path, files: list[str]) -> None:
    sources = [f for f in files if f.endswith(WEB) and not f.endswith(("package-lock.json", "tsconfig.json"))]
    out = run(
        [
            "npx",
            "-y",
            "@biomejs/biome@2.6.5",
            "lint",
            f"--config-path={STANDARDS / 'typescript' / 'biome.json'}",
            "--reporter=json",
            "--max-diagnostics=none",
            *sources,
        ],
        repo,
    )
    diagnostics = json.loads(out or "{}").get("diagnostics", [])
    counted(
        collections.Counter(f"{d.get('severity')} {d.get('category')}" for d in diagnostics), "Biome (standard rules)"
    )

    if "package.json" in files:
        out = run(
            ["npx", "-y", "-p", "node@24", "-p", "knip@latest", "knip", "--no-progress", "--reporter", "compact"], repo
        )
        sections = re.findall(r"^(Unused [^(]+|Unlisted [^(]+|Duplicate [^(]+)\((\d+)\)$", out, flags=re.MULTILINE)
        summary = ", ".join(f"{name.strip().lower()} {n}" for name, n in sections) or "nothing unused"
        print(f"- **Knip (unused files/exports/dependencies):** {summary}")


# -- rust ---------------------------------------------------------------------


def lint_flags() -> list[str]:
    """Clippy flags equivalent to the [lints] tables in Cargo.fragment.toml."""
    lints = tomllib.loads((STANDARDS / "rust" / "Cargo.fragment.toml").read_text(encoding="utf-8"))["lints"]
    ordered: list[tuple[int, str, str]] = []
    for tool, table in lints.items():
        for name, value in table.items():
            level, priority = (value, 0) if isinstance(value, str) else (value["level"], value.get("priority", 0))
            lint = name if tool == "rust" else f"{tool}::{name}"
            ordered.append((priority, LEVELS[level], lint))
    return [part for _, flag, lint in sorted(ordered, key=lambda item: item[0]) for part in (flag, lint)]


def crates(files: list[str]) -> list[str]:
    """Top-level Cargo manifests, skipping nested crates and test fixtures."""
    manifests = [f for f in files if f.endswith("Cargo.toml") and not is_test(f) and "/fuzz/" not in f]
    dirs = sorted(str(Path(m).parent).replace("\\", "/") for m in manifests)
    return [d for d in dirs if not any(d != o and (o == "." or d.startswith(o + "/")) for o in dirs)]


def wsl_path(path: Path) -> str:
    drive, rest = path.drive, path.as_posix()[len(path.drive) :]
    return f"/mnt/{drive[0].lower()}{rest}" if drive else path.as_posix()


def rust(repo: Path, files: list[str]) -> None:
    for crate in crates(files):
        name = f"{repo.name}-{crate.replace('/', '-')}".strip("-.")
        clippy = ["cargo", "clippy", "--all-targets", "--message-format", "json", "-q", "--", *lint_flags()]
        machete = ["cargo", "machete"]
        if shutil.which("cargo"):
            env = {
                **os.environ,
                "CLIPPY_CONF_DIR": str(STANDARDS / "rust"),
                "CARGO_TARGET_DIR": str(WORK / "target" / name),
            }
            messages, unused = run(clippy, repo / crate, env), run(machete, repo / crate)
        elif shutil.which("wsl"):
            messages, unused = through_wsl(repo / crate, name, clippy, machete)
        else:
            print(f"- **Clippy ({crate}):** skipped, no cargo found")
            continue
        codes: collections.Counter[str] = collections.Counter()
        for line in messages.splitlines():
            if line.startswith("{"):
                message = json.loads(line)
                if message.get("reason") == "compiler-message" and message["message"].get("code"):
                    codes[f"{message['message']['level']} {message['message']['code']['code']}"] += 1
        counted(codes, f"Clippy, standard lints ({crate})")
        verdict = (
            "none" if "didn't find any unused" in unused else (unused.strip().splitlines() or ["not installed"])[-1]
        )
        print(f"  - cargo-machete unused dependencies: {verdict}")


def through_wsl(crate: Path, name: str, clippy: list[str], machete: list[str]) -> tuple[str, str]:
    WORK.mkdir(parents=True, exist_ok=True)
    script = WORK / f"{name}.sh"
    script.write_text(
        "\n".join(
            [
                'export PATH="$HOME/.cargo/bin:$PATH"',
                f"cd {shlex.quote(wsl_path(crate))}",
                f"export CLIPPY_CONF_DIR={shlex.quote(wsl_path(STANDARDS / 'rust'))}",
                f'export CARGO_TARGET_DIR="$HOME/.cache/standards-scan/{name}"',
                f"{shlex.join(clippy)} 2>/dev/null",
                "echo '=====MACHETE====='",
                f"{shlex.join(machete)} 2>&1",
            ]
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    out = run(["wsl", "--", "bash", wsl_path(script)], crate)
    messages, _, unused = out.partition("=====MACHETE=====")
    return messages, unused


# -- duplication ---------------------------------------------------------------


def duplication(repo: Path) -> None:
    output = WORK / "jscpd" / repo.name
    shutil.rmtree(output, ignore_errors=True)
    run(
        [
            "npx",
            "-y",
            "jscpd@5",
            "--config",
            str(STANDARDS / "jscpd.json"),
            "--reporters",
            "json",
            "--output",
            str(output),
            ".",
        ],
        repo,
    )
    report = output / "jscpd-report.json"
    if not report.exists():
        print("- **Duplication (jscpd):** no report")
        return
    data = json.loads(report.read_text(encoding="utf-8"))
    total = data["statistics"]["total"]
    print(
        f"- **Duplication (jscpd):** {total['clones']} clone(s), {total['duplicatedLines']} of {total['lines']} lines "
        f"({total['percentage']:.1f}%)"
    )
    for clone in sorted(data["duplicates"], key=lambda c: -c["lines"])[:3]:
        first, second = clone["firstFile"], clone["secondFile"]
        print(f"  - {clone['lines']} lines: `{first['name']}:{first['start']}` = `{second['name']}:{second['start']}`")


def scan(path: str) -> None:
    repo = HOME / path
    print(f"\n## {path}\n")
    if not (repo / ".git").exists():
        print("- missing")
        return
    files = tracked(repo)
    suffixes = {Path(f).suffix for f in files}
    volume(repo, files)
    if suffixes & {".py", ".pyw"}:
        python(repo, files)
    if suffixes & {".ts", ".tsx", ".js", ".mjs", ".jsx"}:
        web(repo, files)
    if ".rs" in suffixes:
        rust(repo, files)
    duplication(repo)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print("# Standards scan")
    for path in sys.argv[1:] or projects():
        scan(path)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
