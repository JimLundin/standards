# Standards

Shared tool configuration for the Python, Rust and TypeScript projects in this
folder, plus a report-only scanner that checks every project against it.

This is a first draft (2026-11-14). No project uses these files yet; see
[Adoption](#adoption) and [Findings from the first scan](#findings-from-the-first-scan).

## Layout

| File | Tool | How a project uses it |
|---|---|---|
| `python/ruff.toml` | Ruff lint + format | `extend = "../standards/python/ruff.toml"` under `[tool.ruff]` |
| `python/pyproject.fragment.toml` | mypy, vulture, dev deps | Copy the sections (neither tool can inherit a shared file) |
| `rust/Cargo.fragment.toml` | rustc + Clippy lint levels | Copy `[lints]` (Cargo cannot inherit lints from outside a workspace) |
| `rust/clippy.toml` | Clippy thresholds | Copy next to `Cargo.toml` |
| `rust/rustfmt.toml` | rustfmt | Copy next to `Cargo.toml` |
| `typescript/biome.json` | Biome lint + format | `"extends": ["../standards/typescript/biome.json"]` |
| `typescript/tsconfig.base.json` | TypeScript compiler | `"extends": "../standards/typescript/tsconfig.base.json"` |
| `jscpd.json` | Duplicate-code detection (all languages) | Used by the scanner |
| `.editorconfig` | Editors | Copy to the project root |
| `scan.py` | All of the above | `python standards/scan.py [project ...]` |

Relative `extend`/`extends` paths assume the project sits directly in this
folder; a nested project such as `keyframe/keyframe` needs one more `../`.
Projects cloned elsewhere (CI) will not find these files, so a project that
needs CI parity should copy the file instead of referencing it.

## What each tool is for

| Concern | Python | Rust | TypeScript / JS |
|---|---|---|---|
| Lint and formatting | Ruff | Clippy, rustfmt | Biome |
| Types | mypy (strict) | the compiler | `tsc` (strict base) |
| Unused code | Ruff `F`/`ERA`, vulture | rustc dead-code lints, cargo-machete (dependencies) | knip (files, exports, dependencies) |
| Duplication | jscpd | jscpd | jscpd |
| Volume | `scan.py` line counts | | |
| Structure | CodeScene Code Health (separate, via the MCP server) | | |

Code Health measures how hard code is to change, not how much of it there is.
Use the unused-code, duplication and volume numbers above to look for code to
delete, and Code Health to look for code to restructure.

## Running the scanner

```bash
python standards/scan.py              # every project in AGENTS.md
python standards/scan.py subset       # one project
```

It needs `git`, `uv` (for `uvx`) and Node with `npx`. knip runs on Node 24,
fetched by `npx -p node@24`. Clippy and cargo-machete use a local `cargo` or,
on Windows without one, `cargo` inside WSL (`cargo binstall cargo-machete`).
Each project is judged by the standard configs, not by its own configuration,
so expect noise where a project has deliberate local settings. Reports and
build output go to the system temp folder; the projects are not modified.

## Adoption

Adopt per project, one tool at a time, starting with the formatter and unused
code checks. Keep project-specific settings in the project, layered on top of
the standard:

- **Python:** keep `line-length`, naming exceptions (`pep8-naming`
  `extend-ignore-names`) and extra `per-file-ignores` in the project's
  `[tool.ruff]` after `extend`. Leave `target-version` unset so Ruff reads
  `requires-python`; forcing an older target made Ruff misreport 3.15 code as
  hundreds of undefined names.
- **Rust:** a crate that needs `unsafe` (FFI bindings) sets
  `unsafe_code = "allow"` in its own `[lints.rust]`. A crate whose house rules
  conflict with a pedantic lint allows that lint locally.
- **TypeScript:** knip needs a `knip.json` listing extra entry points (files
  started as processes or loaded from HTML); without it, it reports them as
  unused files.

## Findings from the first scan

See [findings.md](findings.md).
