# Findings (2026-11-14)

Results of running the standard configs against all seven projects (each
project judged by the standard, not by its own settings), plus manual
spot-checks. No project has adopted the standard yet.

## Volume and comments

| Project | Code (non-blank lines) | Comment lines |
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
