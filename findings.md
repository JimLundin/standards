# Findings (2026-11-14)

Results of running the standard configs against all seven projects (each
project judged by the standard, not by its own settings), plus manual
spot-checks. No project has adopted the standard yet.

## Volume and comments

| Project | Code (non-blank lines) | Comment lines (scc) |
|---|---|---|
| workspace | Python 27.6k | 12% |
| companion | TypeScript 25.3k | 11% |
| subset | Rust 14.8k | 4% |
| keyframe | Python 5.6k | 16% |
| sop | Rust 2.0k, Python 1.4k | Rust 17%, Python 21% |
| liquid-glass | JS 1.8k, CSS 0.5k | 11–17% |
| opendpm | Python 0.9k | 15% |

Comment lines include Python docstrings. subset's `docs/reviews/` holds a
further ~17k lines of copied code, excluded here.

## Lint findings under the standard

| Project | Ruff | Clippy | Biome |
|---|---|---|---|
| workspace | 3,295 | | |
| subset | 1,476 | 1,168 | |
| keyframe | 631 | | |
| sop | 392 | 232 | |
| opendpm | 28 | | |
| liquid-glass | 8 | | 1,401 |
| companion | | | 6,876 |

Removing the docstring and line-length rules cut Ruff findings by about
two thirds (workspace 10,610 → 3,295). What remains is mostly:

- **`S101` in tests**, which goes once each project adds its local
  `tests/**` ignore.
- **keyframe:** relative imports (`TID252`, 157).
- **opendpm:** `print` in command-line code (`T201`, 18).
- **Biome nursery rules** asking for explicit types and named functions
  (about 1,800 in companion).
- **Clippy:** `redundant_pub_crate` (512 in subset) and `or_fun_call` (140).

## Unused and duplicated code

Little to delete; volume is not coming from dead code or copy-paste.

- **Duplication** is under 2% everywhere (jscpd, 70-token minimum).
  `workspace/tests/layouts.py` repeats about 130 lines of
  `settings/layout.py`.
- **vulture** reports 176 items in workspace, 17 in sop, 11 in keyframe and
  7 in opendpm. Spot-checked workspace items are used dynamically (Qt
  slots, callbacks), so expect a whitelist per project.
- **knip (companion):** 18 unused exports and 6 unused exported types look
  real. Its unused files and dependencies are false positives until a
  `knip.json` lists the extra entry points.
- **cargo-machete:** no unused Rust dependencies.

## Lessons from drafting

- Forcing an older Ruff `target-version` produced 337 false undefined-name
  errors on Python 3.15 code; the target comes from `requires-python`.
- Biome's `all` preset turned on every framework domain (394 Qwik errors in
  a project without Qwik), so the standard switches framework domains off.
- Shared Ruff per-file-ignores never match, because Ruff resolves them
  relative to the shared file.

## Tooling notes

- Global Node is 20.10 (Nodist); the latest stable is 26. knip and jscpd 4
  need a newer Node (`npx -p node@26 knip` works); jscpd 5 runs on 20.
- uv is 0.7.2; the latest is 0.13.
- `tokei` and `cargo-machete` are installed in WSL.

## Additional tools evaluated

Every tool below runs locally with no account. Tools needing an outside
service or a restrictive licence (CodeScene, SonarQube, CodeQL) were not
evaluated. MegaLinter was not run: it bundles its own tool versions and
needs Docker.

| Tool | Verdict | Reason |
|---|---|---|
| scc | Adopt | One binary, no network. Counts Python docstrings as comments and other strings as code (tokei counts docstrings as code). `--hotspots`, `--coupling` and `--by-author` cover git-history analysis. |
| import-linter | Adopt where a project has layers | About 1 s per run, little config, parses `lazy import`. keyframe: three imports contradict the layer diagram in `docs/DESIGN.md`. workspace: six contracts matched its own checker on the clean tree but missed two of seven planted violations (single-file top-level modules, and the dynamic-import ban, which it cannot express). |
| tach | Use `check-external` once | Layer rules silently skip `visibility`/`cannot_depend_on` checks when layers already allow an import. `check-external` on workspace: `mypy` and `ruff` are runtime dependencies the code never imports, `truststore` is unused, `shiboken6` is imported but undeclared. |
| complexipy | Optional report | Python cognitive complexity; the worst functions match Ruff's C901 and lizard. Ruff, Biome and Clippy already enforce complexity. |
| Qlty CLI | `smells` as a report at most | Works offline after `qlty init`, but sends telemetry by default (`QLTY_TELEMETRY=off`). As a runner, `qlty check` pins old tool versions (Ruff rejects `py315`, Rust cannot read edition 2024) and reported "No issues" while every Clippy run failed. |
| lizard | Skip | Duplicates Ruff, Biome and Clippy complexity rules; flags flat Rust `match` dispatch. |
| tokei | Replaced by scc | Docstrings count as code; Rust doc comments are hidden as embedded Markdown. |
| code-maat | Skip | Needs Java (ran in Docker); scc's history reports cover churn and coupling. |
| ast-grep | Skip as a standard | Fast, native on Windows, but has no maintained rule catalogue, so every rule would be our own. |
| Semgrep CE | Skip for code | Code findings repeat Ruff's S rules or Clippy, or are noise; cannot parse Python 3.15 `lazy import`; rule packs are under a non-OSI licence. |
| dependency-cruiser | Skip for now | Does not support TypeScript 7 yet; companion's own architecture test already covers cycles. |
| cargo-modules | Skip | Its cycle check works on items, so every crate "fails" on a type and its own methods. |

### Findings worth acting on

- **opendpm CI:** `.github/workflows/build-database.yml:60` puts
  `${{ inputs.version_id }}` straight into a shell `run:` step (script
  injection), and 16 action references are not pinned to a commit. workspace
  has 6 unpinned actions. Candidates for a CI check: zizmor, actionlint.
- **Module cycles:** sop `document.rs` and `parser.rs` import each other;
  keyframe's `expr` lazily imports `check`, which imports `expr`.
- **workspace dependencies:** `mypy` and `ruff` as runtime dependencies,
  unused `truststore`, undeclared `shiboken6`.
- **Lint suppressions without a reason:** 5 across the Python projects. Ruff
  has no rule that requires one (Clippy does).
- **companion runs no lint:** its `biome.json` disables the linter.
- **Hotspots (scc, complexity × commits):** workspace
  `desktop_ui/island_surface.py`, `desktop_bar.py`, `keyboard/win.py`.
