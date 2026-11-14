# Findings from the first scan (2026-11-14)

Output of `python standards/scan.py` against all seven projects, with the
standard configs as drafted on this date, plus manual spot-checks. Counts are
what the standard *would* report; no project has adopted it yet.

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

## Unused and duplicated code

Little to delete. Volume is not coming from dead code or copy-paste.

- **Duplication** is under 2% everywhere (jscpd, 70-token minimum).
  - Real candidate: `workspace/tests/layouts.py` repeats about 130 lines of
    `settings/layout.py`.
  - subset's 1.6% is shared boilerplate across `tests/cases/*` fixtures, which
    are meant to be self-contained.
- **vulture (80%)** finds one item per Python project at most. At 60% it
  lists 187 items in workspace, but spot-checked functions are used by tests or
  dynamically, so 80% is the right default. It flags sop's `DataclassInstance`
  as unused; that is a false positive (used in a string annotation).
- **knip (companion)** reports 18 unused exports and 6 unused exported types,
  which look real. Its 6 "unused files" and 2 "unused dependencies" are false
  positives: `serve.ts` is started as a separate process and `common.js` is
  loaded from HTML, so knip needs a `knip.json` with those entry points.
- **cargo-machete** finds no unused Rust dependencies.

## Lint: what the standard would surface

| Project | Findings | Mostly | Verdict |
|---|---|---|---|
| opendpm | 4 | minor | Ready to adopt |
| sop (Python) | 14 | import order, a few simplifications | Ready to adopt |
| sop (Rust) | 66 + 22 | `cast_possible_truncation` (27) in the parser; `unsafe_code` in the PyO3 bindings | Adopt with `unsafe_code = "allow"` in `bindings` |
| liquid-glass | 5 Ruff, 60 Biome | `noRedundantUseStrict` (30), `noShadowRestrictedNames` (8) | Check whether the files are ES modules before acting on "use strict" |
| keyframe | 352 | relative imports `TID252` (157), long lines (60), exception names `N818` (23) | Decide on relative imports first |
| companion | 126 Biome | non-null assertions (41), `import type` (30), comma operator (23) | Adopt; the comma-operator hits deserve a look |
| subset | 307 Clippy, 79 Ruff | `ignored_unit_patterns` (121), `explicit_iter_loop` (64) | Conflicts with subset's own Rust rules (`()` only at library boundaries), so allow those two lints locally |
| workspace | 1229 | line length (857 at 120 vs its own 150), Windows/Qt API names `N8xx` (329) | Keep its `line-length` and naming exceptions as local overrides; about 40 real findings remain |

## Lessons for the standard itself

- **Python version:** never force a Ruff `target-version` from outside the
  project. With an older target, Ruff misreported 3.15 code as 337 undefined
  names in workspace and keyframe.
- **Rust:**
  - `unsafe_code = "deny"` needs a local allow for FFI crates.
  - `print_stdout`/`print_stderr` fire on every CLI binary, so they were taken
    out of the standard.
- **Biome 2.6:** the `recommended` field is deprecated; use `"preset": "recommended"`.
- **Node:** knip needs Node 22+, and jscpd 4 does not run on the installed
  Node 20. jscpd 5 (Rust engine) does, and knip runs via `npx -p node@24`.
  companion already pins Node 24.22 in `.node-version`; the global default is
  still 20.10.
- **Copied snapshots:** subset's `docs/reviews/` is excluded everywhere. Any
  other project that keeps reference copies of code should be excluded the
  same way.

## Suggested next steps

1. Adopt in opendpm and sop first; they are nearly clean.
2. Decide two style questions: relative imports in keyframe, and whether 120
   or 150 is the standard Python line length.
3. Add `knip.json` to companion and review the 24 unused exports.
4. Remove the duplicated layout data in `workspace/tests/layouts.py`.
