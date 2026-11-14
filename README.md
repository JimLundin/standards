# Standards

Shared tool configuration for the Python, Rust and TypeScript projects in
this folder, plus a report-only scanner that checks every project against
it. No project has adopted it yet; see [findings.md](findings.md).

## Principles

1. **Start from each tool's strictest preset.** Ruff `ALL`, basedpyright
   `all`, Clippy's groups, Biome's `all`, pytest's `strict`, TypeScript's
   `strict`. Configure as little as possible on top.
2. **Only remove a rule when it contradicts another rule or the formatter,
   or cannot apply** (for example Biome's framework domains). Each removal
   is commented in the config.
3. **Extra strictness goes on top, labelled,** where a tool keeps useful
   checks outside its presets (Clippy restriction lints, TypeScript flags
   beyond `strict`).
4. **Latest releases, nightly where available:** Python 3.15 (tested on the
   3.16 pre-release), Rust nightly with edition 2024, TypeScript 7, Node 26,
   latest Ruff, Biome and friends. Projects lock versions and upgrade
   regularly.
5. **80-column lines** in every language, so code reads on a phone.
6. **TypeScript uses only erasable syntax** (`erasableSyntaxOnly`): no
   enums, namespaces or parameter properties, so Node runs `.ts` directly.
7. **Coverage is backed by mutation and property testing.** A 100% branch
   coverage bar only proves code ran; mutation tests prove the tests notice
   changed behaviour, and property tests check rules over generated input.

## Layout

| File | Contents | How a project uses it |
|---|---|---|
| `python/pyproject.toml` | Ruff, basedpyright, pytest, coverage, dev dependencies | Ruff: `extend = "../standards/python/pyproject.toml"`. Copy the other sections (one or two lines each); they cannot inherit. |
| `rust/Cargo.fragment.toml` | Lint levels, proptest | Copy into `Cargo.toml` (Cargo cannot inherit lints from outside a workspace) |
| `rust/rust-toolchain.toml` | Nightly toolchain | Copy next to `Cargo.toml` |
| `rust/rustfmt.toml` | 80 columns | Copy next to `Cargo.toml` |
| `typescript/tsconfig.base.json` | Compiler flags beyond TS 7's defaults | `"extends": "../standards/typescript/tsconfig.base.json"` |
| `typescript/biome.json` | Lint: all rules, nursery, no framework domains | `"extends": ["../standards/typescript/biome.json"]`, then enable the project's framework domain |
| `typescript/package.fragment.json` | Node version, scripts, dev dependencies | Merge into `package.json` |
| `jscpd.json` | Duplicate-code detection, all languages | Used by the scanner |
| `.editorconfig` | Editor basics | Copy to the project root |
| `scan.py` | Runs everything above | `python standards/scan.py [project ...]` |

Relative `extend`/`extends` paths assume the project sits directly in this
folder (a nested project such as `keyframe/keyframe` needs one more `../`).
CI checkouts will not find these files, so a project that runs checks in CI
should copy the file instead.

## Tools by concern

| Concern | Python | Rust | TypeScript |
|---|---|---|---|
| Lint, format | Ruff | Clippy, rustfmt | Biome |
| Types | basedpyright (`all`) | the compiler | `tsc` |
| Unit tests, coverage | pytest, coverage (100% branch) | `cargo test`, cargo-llvm-cov | `node --test` (built-in coverage) |
| Property tests | hypothesis | proptest | fast-check |
| Mutation tests | mutmut | cargo-mutants | Stryker |
| Unused code | Ruff, vulture | rustc lints, cargo-machete | knip |
| Duplication | jscpd | jscpd | jscpd |
| Volume | `scan.py` | `scan.py` | `scan.py` |
| Structure | CodeScene Code Health (MCP server) | same | same |

Mutation testing has no pass mark yet. Equivalent mutants make 100%
unreachable, so set a bar per project after its first run.

## Running the scanner

```bash
python standards/scan.py              # every project in AGENTS.md
python standards/scan.py subset       # one project
```

It needs `git`, `uv` (for `uvx`) and Node with `npx`; knip runs on Node 26
through `npx -p node@26`. Clippy and cargo-machete use a local `cargo`, or
`cargo` inside WSL on Windows. Each project is judged by the standard
configs, not its own, so the report shows what adopting the standards would
surface. Reports and build output go to the system temp folder; projects
are not modified.

## Adoption notes

- **Python:** keep project-specific settings (naming exceptions for
  Windows or Qt APIs, for example) in the project's `[tool.ruff]` after
  `extend`. Add `[tool.ruff.lint.per-file-ignores] "tests/**" = ["S101"]`
  locally: Ruff resolves per-file-ignores relative to the file that
  defines them, so the shared file cannot do it. Leave `target-version`
  unset; Ruff reads `requires-python`.
- **Rust:** a crate that needs `unsafe` (FFI bindings) allows it locally;
  so does a crate whose house rules conflict with a lint.
- **TypeScript:** knip needs a `knip.json` listing extra entry points
  (files started as processes or loaded from HTML).
