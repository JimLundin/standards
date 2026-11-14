# Standards

Shared tool configuration for the Python, Rust and TypeScript projects in
this folder. No project has adopted it yet; see [findings.md](findings.md).

## Principles

1. **Existing tools before our own.** The standard is configuration for
   established tools. Nothing here is custom tooling.
2. **Start from each tool's strictest preset** (Ruff `ALL`, basedpyright
   `all`, Clippy's lint groups, Biome `all`, pytest `strict`, TypeScript 7's
   strict defaults) and configure as little as possible. Remove a rule only
   when it conflicts with the formatter or with another rule of the same
   tool, or cannot apply (Biome's framework domains). Add strictness on top
   where a tool keeps useful checks outside its presets.
3. **The code is the specification.** No lint may require comments or
   docstrings: prose that restates the code drifts from it and misleads
   whoever reads both. Required prose is limited to what a tool demands
   because the code cannot express it: Rust's safety invariants for
   `unsafe` (`undocumented_unsafe_blocks`, `# Safety`), Rust's `# Errors`
   and `# Panics` sections, and the reason on a lint suppression. Comment
   volume is measured and pushed down.
4. **Formatters own layout.** Lines are 80 columns so code reads on a
   phone; the formatter wraps them, and no lint checks line length.
5. **Latest releases, nightly where available:** Python 3.15 (also tested
   on the 3.16 pre-release), Rust nightly with edition 2024, TypeScript 7,
   Node 26, and the latest Ruff, Biome and other tools.
6. **TypeScript uses only erasable syntax** (`erasableSyntaxOnly`): no
   enums, namespaces or parameter properties, so Node runs `.ts` directly.
7. **Measure tests, do not target them.** Coverage, mutation and property
   tests show where tests are weak. There is no coverage or mutation-score
   threshold, because chasing a number distorts the code and the tests.
8. **Languages follow their own conventions.** Rules that differ between
   languages are not reconciled.

## Layout

| File | How a project uses it |
|---|---|
| `python/pyproject.toml` | Ruff: `extend = "../standards/python/pyproject.toml"` under `[tool.ruff]`. Copy the other sections; basedpyright, pytest and coverage cannot inherit. |
| `rust/Cargo.fragment.toml` | Copy into `Cargo.toml`; Cargo cannot inherit lints from outside a workspace. |
| `rust/rust-toolchain.toml`, `rust/rustfmt.toml` | Copy next to `Cargo.toml`. |
| `typescript/tsconfig.base.json` | `"extends": "../standards/typescript/tsconfig.base.json"` |
| `typescript/biome.json` | `"extends": ["../standards/typescript/biome.json"]`, then turn on the project's framework domain. |
| `typescript/package.fragment.json` | Merge into `package.json`. |
| `jscpd.json` | `npx jscpd --config ../standards/jscpd.json .` |
| `.editorconfig` | Copy to the project root. |

Relative paths assume the project sits directly in this folder (nested
projects such as `keyframe/keyframe` need one more `../`). CI checkouts do
not have this folder, so a project that runs checks in CI copies the file.

## Tools

| Concern | Python | Rust | TypeScript |
|---|---|---|---|
| Format | `ruff format` | `cargo fmt` | `biome format` |
| Lint | `ruff check` | `cargo clippy` | `biome lint` |
| Types | `basedpyright` | the compiler | `tsc` |
| Tests, coverage | `pytest`, `coverage` | `cargo test`, `cargo llvm-cov` | `node --test --experimental-test-coverage` |
| Property tests | hypothesis | proptest | fast-check |
| Mutation tests | `mutmut run` | `cargo mutants` | `stryker run` |
| Unused code | Ruff, `vulture` | rustc, `cargo machete` | `knip` |
| Duplication | `jscpd` | `jscpd` | `jscpd` |
| Volume, comment lines | `tokei`, `scc` | `tokei`, `scc` | `tokei`, `scc` |
| Structure | CodeScene Code Health | same | same |

## Adoption notes

- **Python:** add `[tool.ruff.lint.per-file-ignores] "tests/**" = ["S101"]`
  in the project. Ruff resolves per-file-ignores relative to the file that
  defines them, so the shared file cannot do it. Keep naming exceptions for
  external APIs (Windows, Qt) in the project too. Leave `target-version`
  unset; Ruff reads `requires-python`.
- **Rust:** a crate that needs `unsafe` (FFI bindings) allows it locally.
- **TypeScript:** knip needs a `knip.json` listing extra entry points
  (files started as processes or loaded from HTML).
