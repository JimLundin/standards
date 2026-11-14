# Findings (2026-11-14)

Results of `python standards/scan.py` against all seven projects, plus manual
spot-checks. Counts are what the standards *would* report; no project has
adopted them yet.

## Volume

| Project | Code (non-blank lines) | Notes |
|---|---|---|
| workspace | Python 27.6k | |
| companion | TypeScript 25.3k | |
| subset | Rust 14.8k | `docs/reviews/` holds a further ~17k lines of copied code (excluded) |
| keyframe | Python 5.6k | |
| sop | Rust 2.0k, Python 1.4k | |
| liquid-glass | JS 1.8k, CSS 0.5k | |
| opendpm | Python 0.9k | |

## Strict presets vs. the first, curated draft

The first draft hand-picked rules; the current standard starts from each
tool's strictest preset. Finding counts:

| Project | Tool | Curated draft | Strict presets |
|---|---|---|---|
| workspace | Ruff | 1,229 | 10,610 |
| subset | Clippy / Ruff | 307 / 79 | 1,168 / 1,704 |
| keyframe | Ruff | 352 | 1,690 |
| companion | Biome | 126 | 6,598 |
| liquid-glass | Biome | 60 | 1,426 |
| sop | Clippy / Ruff | 88 / 14 | 232 / 609 |
| opendpm | Ruff | 4 | 104 |

Most of the increase is volume from a few rules, not new kinds of problem:

- **Line length at 80:** 4,895 of workspace's findings; most projects were
  written at 100–150.
- **Docstrings (`D1xx`, `DOC201`):** every public function, method and
  return value must be documented.
- **`S101` in tests:** disappears once each project adds its local
  `tests/**` ignore.
- **Biome nursery rules:** `useExplicitType`, `useExplicitReturnType` and
  `useNamedFunction` (about 1,800 in companion).
- **Clippy nursery:** `redundant_pub_crate` (512 in subset) and
  `or_fun_call` (140).

### Rules that may not belong in a strict standard

Strict means more checks, not contradictory ones. These are worth a
decision before adoption:

- **Biome `noTernary`** (517 in companion) bans `a ? b : c` outright, while
  Ruff's `SIM108` asks for the ternary form.
- **Biome `useCapitalizedConstructors`** (699, nursery): needs checking for
  false positives.
- **Clippy `redundant_pub_crate`** (nursery) is documented as conflicting
  with rustc's `unreachable_pub`. It is only safe while `unreachable_pub`
  stays off.
- **subset's own Rust rules** require patterns Clippy pedantic flags
  (`ignored_unit_patterns`, `explicit_iter_loop`), so subset needs local
  allows.

### Problems with the first draft, now fixed

- Forcing an older Ruff `target-version` produced 337 false undefined-name
  errors on Python 3.15 code; the target now comes from `requires-python`.
- Biome's `all` preset turned on every framework domain (394 Qwik errors in
  a project with no Qwik); the standard now switches framework domains off.
- Shared Ruff per-file-ignores never match, because Ruff resolves them
  relative to the shared file; projects add their own.

## Unused and duplicated code

Little to delete. Volume is not coming from dead code or copy-paste.

- **Duplication** is under 2% everywhere (jscpd, 70-token minimum).
  - Real candidate: `workspace/tests/layouts.py` repeats about 130 lines of
    `settings/layout.py`.
  - subset's 1.6% is boilerplate shared by self-contained test fixtures.
- **vulture at every confidence level** reports 176 items in workspace, 17
  in sop, 11 in keyframe and 7 in opendpm. Spot-checked workspace items are
  used dynamically (Qt slots, callbacks), so expect a whitelist per project.
- **knip (companion):** 18 unused exports and 6 unused exported types look
  real. Its 6 unused files and 2 unused dependencies are false positives
  until a `knip.json` lists the extra entry points (`serve.ts` runs as its
  own process, `common.js` is loaded from HTML).
- **cargo-machete:** no unused Rust dependencies.

## Tooling notes

- The global Node is 20.10 (Nodist); companion pins 24.22; the latest stable
  is 26. knip and jscpd 4 need newer Node; the scanner uses
  `npx -p node@26` and jscpd 5 (Rust engine).
- uv is 0.7.2; the latest is 0.13.
- `scan.py` passes the strict Ruff standard. basedpyright `all` still
  reports 46 issues in it, nearly all `reportAny` from untyped `json.loads`
  results.

## Suggested next steps

1. Decide on the four rules listed above.
2. Adopt in opendpm first (smallest), then sop.
3. Update Node (global) and uv.
4. Add `knip.json` to companion and review the 24 unused exports.
5. Remove the duplicated layout data in `workspace/tests/layouts.py`.
