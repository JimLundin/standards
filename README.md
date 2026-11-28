# Standards

Shared tool configuration and checks for Python, Rust and TypeScript projects.

Each config file can be copied to its usual place in a project, and the scripts use a project's own copy when it has one. The repository can be copied as a whole, since the scripts only use paths relative to it. A project names the profiles it follows in its `project.toml` in the home, and finds this repository's checkout by its root commit like any other project.

## Running the checks

```bash
python/check.sh [commit|step|release] [--no-cache|--verify|--affected] [project]
rust/check.sh …
typescript/check.sh …
```

- `commit`, the default, runs the exceptions, format, lint, type and structure checks.
- `step` adds the tests, and in TypeScript the dead-code check of the tests.
- `release` adds mutation testing, thorough property tests, slow and ignored tests with their coverage, one unit, duplication and volume.

`step` and `release` run only in CI. On a machine the owner allows them on, set `STANDARDS_LOCAL_TIERS=1`; anywhere else either tier stops before its first unit and names the variable. `--verify` and `--affected` run nothing, so they need neither.

One run that runs units at a time per user: each takes an `flock` on `run.lock` in the standards' cache directory (`STANDARDS_CACHE` overrides it), so the lock covers every checkout and worktree. A second run prints the holder's pid and project, waits for it to exit, then starts. The kernel frees the lock when the holder exits, killed or not, so a stale lock can't block; units and the sccache server start without it, so a process that outlives the run doesn't hold it. Without `flock` (util-linux), as under a Git Bash that lacks it, a run says so and runs without the lock. `--verify` and `--affected` take no lock.

A unit that can't run, such as one whose tool isn't installed, is skipped; in CI (`CI` set, as GitHub Actions sets it) it fails instead, so CI passes no tree with a unit it didn't run.

`--verify` runs nothing: it takes every unit key of the tier and fails each unit without a recorded pass, naming its scope and key. A queue runs it on the commit it is about to land.

`--affected` runs nothing either: it prints, one a line, the packages whose units the tier would check, those without a recorded pass, which are the packages changed since their last pass and the packages that depend on them. While iterating, check only those.

The scripts' own tools live in `checks`, a uv project that depends on `ordered` and passes the Python standard itself, so every language's checks need uv.

The repository as a whole is no one language's project. Its own gate is each check run on its own part, from the repository's root:

```bash
python/check.sh commit checks
python/check.sh commit python/ordered
rust/check.sh commit rust/measure
typescript/check.sh commit typescript
typescript/check.sh commit typescript/oxlint-plugins
```

`typescript/oxlint-plugins` is a package of its own, so its checks need its dependencies installed first, with `npm ci` in it.

The trees under `typescript/fixtures/` are the inputs of the `typescript-fixtures` suite, which checks each as a project of its own; the TypeScript part's checks leave them out.

## Tool versions

`tools.env` pins the version of every tool the checks run or fetch, one `NAME=version` per line so CI can read it too. `uvx` and `npx` fetch the pinned version. Before a run, each installed tool, such as uv, Node, nextest, sccache, `rust-decisions` or the project's Stryker, vitest and `@effect/vitest` with the Effect beside it, is compared with its pin, and a mismatch fails at once with the command that installs the pinned version. Python is the one uv resolves: `check.sh` sets `UV_PYTHON` to the `PYTHON` pin, so the standards' checks, a Python project's checks and its key use that interpreter whatever `python3` is on `PATH`, and a suite runs with it first on `PATH`.

## Units and recorded passes

A tier runs as units, each a check over a scope:

- in Rust, the lint, `no_std` core, API, shell and test checks of each package, and the exceptions, format, shell share and release checks of the whole project;
- in Python and TypeScript, each check of the project, where dead code is two units, `unused` and `unused-tests`: in Python over the source files and over the test files, and in TypeScript knip's production run at `commit` and its default run at `step`;
- each suite in `checks.toml`.

A unit's key hashes the check, the git tree of the standards, the toolchain's version (`cargo -V` and `rustc -V`, `uv --version` or `node --version`), the pinned version of the tool the check runs, and the git blobs of the files it reads:

- A whole-project unit reads every file, except a Python unit with a side. `checks units` takes `--side=<check>=sources|tests` for a project check: the `sources` side reads every file but the Python test files, and the `tests` side every file but the Python source files. Python's `unused` unit has the `sources` side and `unused-tests` the `tests` side, so a test edit reruns only `unused-tests`, a source edit only `unused`, and an edit to config such as `pyproject.toml` or `exceptions.toml` both.
- A Rust package reads every file in its folder, Rust or not, such as its manifest and test fixtures; every file of its workspace dependencies, from `cargo metadata`; and every project file outside the packages and the docs (`*.md`, `docs/`, licences, `.github/`), such as `Cargo.lock`, the root `Cargo.toml` or `rust-toolchain.toml`.

So a test fixture reruns its package and the packages that depend on it, and a lockfile or root manifest change reruns every package.

A pass is recorded as a git note on `refs/notes/checks` whose annotated object name is the key, so one `git notes list` reads every pass. A unit whose key has a pass reports `passed (recorded)` without running. Failures are never recorded. The keys are taken again after a check, and a pass is recorded only if its key still matches. `--no-cache` runs every unit, and still records its passes.

The notes are `checks notes`'s alone: `lookup` lists the recorded keys, `record` adds passes, `fetch` merges `origin`'s notes by union (`git notes merge -s cat_sort_uniq`), and `push`, after a run that recorded one, pushes them, merging and retrying when another run pushed first. A project without `origin` keeps them local. Its notes commits carry the standards' own identity, so a CI runner needs no git config. The standards keep their own index of the project's files under the user's cache directory (`STANDARDS_CACHE` overrides it), so listing the files doesn't touch the project's index.

A Rust package check runs once over the whole workspace when any package's pass is missing: cargo then resolves features once and rebuilds only what changed, where selecting packages with `-p` would resolve their features apart from the workspace's and rebuild dependencies. nextest builds the workspace's tests and runs only the unproven packages' with a filterset. A failed run credits a package only on evidence that the check reached it and found nothing in it:

- the tests, where nextest built every test binary (`Starting`) and ran to its summary, credit each package without a failed test; a failed test build or build script, a run cut short, or the `cargo test` fallback credits none;
- the lint and the `no_std` build credit only the packages cargo built a target of, by its JSON messages;
- the core, API and shell analyses credit nothing unless the analysis printed its last line.

Each error and finding is then credited to a package: its location or path to the package whose directory holds it, and cargo's `could not compile` or a failed build script to a package and its dependents. An error or finding no workspace package owns credits none.

## Suites

A project declares its own suites in `checks.toml`. Each `[[suite]]` has a `name`, a `command` run by bash from the project root, and `[[suite.when]]` entries of a `tier` with `paths` globs, in Rust `packages`, or neither. A suite is a unit at the lowest of those tiers and above, and its key reads what it reads: the files its `paths` match and the inputs of its `packages` (their own files, their workspace dependencies', and the files outside the packages, such as `Cargo.lock`), or the whole project when an entry names neither, and the pins of its `tools`, names from `tools.env`. A suite that builds a crate names it in `packages`, and one that runs Node names `tools = ["NODE"]`.

## Exceptions

Exceptions live only in a project's `exceptions.toml`; suppression comments and weakened configs fail the checks. Each entry has a path glob, a rule and a reason; `exceptions.toml` at the root lists the rules. A file whose comments must stay takes rule `comment`, in any language. A Python `unused` exception can take `names`, a list of qualified item names such as `OrderedMapping.keys`, and then covers only vulture's findings for those items in its path; without `names` it covers every finding in the path. An item's qualified name joins the classes and functions it sits in with its own name, so an attribute set in `__init__` is `Class.__init__.attr`. A name that matches no finding in a file vulture read fails the unit. A TypeScript lint exception names its rule `lint/<plugin>/<rule>`, as Oxlint prints it, such as `lint/typescript/no-floating-promises` or `lint/eslint/no-bitwise`; `checks oxlint-config` writes a config under `node_modules/.cache/standards/` that extends the project's or the standard's config and turns each such rule off for its path, anchored at the project root, and the lint unit runs Oxlint with it.

## Comments

The exceptions check fails every comment in a Python, Rust or TypeScript source file, by file and line: a line or block comment, a doc comment or a Python docstring. Shell scripts and config files are out of scope. A comment is prose the next reader must trust unchecked, so the fix is to name, type or restructure the code until it needs none. Rust and TypeScript are parsed with tree-sitter, so `//` inside a string, template literal or regex literal is no comment. The check keeps by itself:

- a Rust `// SAFETY:` comment directly before an `unsafe` block, or before a statement whose first line opens one, which `clippy::undocumented_unsafe_blocks` requires;
- a licence header: the file's first comment block, before any code, naming `SPDX-License-Identifier` or `Copyright`.

A shebang and Rust's `#[expect(..., reason = "...")]` are not comments. A suppression comment is reported once, as a suppression. Any other comment that must stay takes a `comment` exception naming its file, with the reason the code can't say it. The Rust fragment allows clippy's `missing_errors_doc` and `missing_panics_doc`, which would demand a doc comment: a function's contract is its signature and its error type.

## Rust

**Layers.** A package declares its layer in its `Cargo.toml` as `layer = "core"` or `layer = "shell"` under `[package.metadata.standards]`, and an undeclared package is core. Core libraries are the pure core, and binaries and shell packages are the imperative shell.

**`no_std` core.** The checks build each core library with all its features for `wasm32v1-none`, where `std` doesn't exist, so a core library must be `#![no_std]` and its dependencies must be too, whichever features are on. Its root declares `#![no_std]` unconditionally, or `#![cfg_attr(not(test), no_std)]`, and `extern crate std` appears only under `#[cfg(test)]`, so no target or feature hands the core `std` and its I/O; these take no exception.

**Plain values.** The same build lints the core libraries with the project's clippy config, which adds `Box`, `Rc`, `Arc` and their `Weak`s to its disallowed types: the core holds plain values, so a recursive type keeps its parts in a `Vec` and refers to them by index. A core file that needs one takes a `box` exception; the shell may use them freely.

**Data-only API.** A core library's public API takes only data: no trait objects, function pointers, `async`, or bounds other than the standard value traits (`Clone`, `Ord`, `Hash`, `Display`, `From` and the like), so the shell can't hand the core an effect through a port, a callback or an iterator. A file that needs one takes an `api` exception.

**Thin shell.** No function in a binary or a shell package may make more than 2 decisions, and once a project makes 20 decisions, the shell may make at most 25% of them. A decision is an `if`, a `match` of more than one arm, a match guard, a `for` or `while` loop, a `let … else` or a run of `&&` or `||`, written in the function, its closures or a macro's arguments; `?`, `.await` and macro expansions are not. `rust-decisions`, in `rust/measure`, counts them from the source; install it with `cargo install --locked --path rust/measure`, and bump its version and `RUST_DECISIONS` in `tools.env` with every change to it. A file takes a `shell` exception for the first rule and `Cargo.toml` for the second. The second is the `shell-share` unit of the whole project, so a merge of two branches that each kept the share is checked again. Mutation testing skips shell-only files.

**Lints.** A project without its own `[lints]` is linted with those of `rust/Cargo.fragment.toml`. The drift check holds a project's `[lints]` to the fragment's: a lint the fragment denies may be set no weaker, and one it allows must be `allow` exactly, at a priority no lower than any stricter entry, so a denied group such as `pedantic` can't override it.

**Flaky tests.** A test that fails only under load takes a `flaky` exception naming the test or a glob of its nextest name. nextest retries just those once, the summary reports a pass on the retry as `flaky`, and retries in a project's own nextest config fail the checks.

**sccache.** `check.sh` sources `rust/build.sh`, and a shell can source it from a project root before plain cargo. Where sccache is installed, cargo compiles through it as `RUSTC_WRAPPER`, whose server `build.sh` starts so a first build never waits on one, into a cache under `~/.cache/sccache` that every worktree shares, unlike a shared target dir, which is unsafe across worktrees. A `RUSTC_WRAPPER` the caller already set wins, and without sccache cargo builds as before. sccache can't cache incremental builds, proc-macros or binaries, so it saves most on dependencies, and a path inside the checkout, such as a build script's `OUT_DIR`, is part of the key, so another worktree misses on the crates that read one. Linking needs nothing: the toolchain links Linux hosts with its bundled `rust-lld`.

## Python

**Layers and purity.** An exhaustive import-linter layers contract puts the core at the bottom, so it imports nothing else of the app. The purity check holds the core to pure standard modules, no effectful builtins such as `open`, `input` or `eval`, and a public API that takes only data: no `Callable`, `Iterable`, `IO`, `type[...]`, `Protocol` or ABC of its own, and no `async`. A pure third-party package takes a `PUR001:<module>` exception.

**Ordered collections.** `python/ordered` is a small package of collections whose iteration order is part of their type: `OrderedCollection`, `OrderedSequence`, `OrderedSet` and `OrderedMapping` extend the collection ABCs with that promise, and `FrozenList`, `FrozenOrderedSet` and `FrozenOrderedDict` implement them, with set and merge operations that keep the left operand's order. Projects copy it or depend on it, and the core may import it.

**Dead code.** Vulture checks the source files and the test files apart, so a use in a test never keeps a source item alive. The test files are the tracked `.py` and `.pyw` files matching `**/tests/**`, `**/test_*.py` or `**/conftest.py`; every other one is a source file. `checks sides` sorts them, and the same globs pick each unit's key. Both units run in `commit` at the `VULTURE` pin. `unused` runs over the sources and reports anything only tests use; `unused-tests` runs over the tests and reports dead test helpers, fixtures and imports. Each drops the findings an `unused` exception covers.

**Immutability.** The immutability check makes `ordered` the vocabulary: no set literals, set comprehensions, `set()` or `frozenset()`, since they iterate in hash order; no `set`, `frozenset`, `AbstractSet` or `Collection` in annotations, since they promise no order; and `FrozenList` and `FrozenOrderedDict` in place of `tuple[T, ...]`, `frozendict` and `MappingProxyType`. Plain `Sequence`, `Mapping` and `Container` stay for inputs that don't depend on order.

## TypeScript

**Lint and format.** oxfmt formats every tracked file it supports, with the project's `.oxfmtrc.json` or else the standard's `typescript/.oxfmtrc.json`, and sorts `package.json`. Oxlint lints with the project's `oxlint.config.ts`, which imports the standard's as `#standards/oxlint` and extends it, or else with the standard's, which extends `@cloudflare/oxlint-config`. Its rules are type-aware through `oxlint-tsgolint` where the project has a `tsconfig.json`. It prints its findings in its `unix` format, one line each, which the lint unit's summary counts. `check.sh` installs Oxlint, `oxlint-tsgolint` and the cloudflare config at their pins into its cache with `npm ci`, from `typescript/oxlint-install/package-lock.json`, which pins their own dependencies. A project merges `typescript/package.fragment.json` into its `package.json`, for TypeScript, its test tools and knip at their pins. The fragment carries no Oxlint or oxfmt, and its one script, `check`, runs only `tsc`: `check.sh` is the one runner of lint, format, tests and mutation, since it alone runs them on the standard's configs.

**Custom rules.** The standard's own lint rules are the Oxlint JS plugin `standards`, in `typescript/oxlint-plugins/`: one module per rule in `rules/`, named for it, and `index.ts`, which lists them. Node loads its `.ts` files by type stripping, and `oxlint.config.ts` loads it from beside itself and turns every rule it lists on, so a new rule is a module and an entry in the index. `no-module-state` reports a mutable binding at module scope and a module-level mutable collection; `readonly-members` a class property or type member without `readonly`; `readonly-types` a mutable array, `Map` or `Set` type. Nondeterminism is native: `no-restricted-globals` bans `Date`, `performance` and `crypto`, and `no-restricted-properties` `Math.random`. Each rule's vitest test runs the pinned Oxlint with only it on over example files, and the package's `test` unit runs them at `step`.

**Dead code.** knip finds unused files, exports, types, enum members and dependencies, on the standard's empty `typescript/knip.json`. Its default `entry` and `project` patterns and its plugins mark which files are production and which are tests, such as vitest's `*.test.*` files and `__mocks__/`. Two units run it, each keyed on every file and on the `KNIP` pin:

- `unused`, at `commit`, runs `knip --production`, which leaves the test files and what only they import out of the analysis. So it reports an export, type or enum member that only tests use.
- `unused-tests`, at `step`, runs knip's default mode, which counts the tests. It reports a helper file that no test imports. It also reports a helper's export that no test uses and an unused devDependency, which production mode skips. Every knip run resolves the whole module graph, so this second run stays out of `commit`.

A project that sets its own `entry` or `project` in its `knip.json` marks its production patterns with a `!` suffix, since production mode reads only those. Production mode counts a helper file outside the test patterns, such as `test/named.ts`, as production, so `unused` reports it as an unused file even when a test imports it. A project with such helpers leaves them out of production with a negated pattern that also takes the suffix, as in `"project": ["**/*.{ts,tsx}!", "!test/**!"]`, set for each workspace.

**Tests.** Tests run on vitest with `it` from `@effect/vitest`, the one test function: `it.effect` for an Effect, `it.prop` for a property over Schemas or Arbitraries. vitest runs on a project's own config, a `vitest.config.*` or the `vite.config.*` vitest reads without one, or else on the standard's `typescript/vitest.config.ts`, which loads `vitest.setup.ts` from beside itself: `check.sh` copies both into `node_modules/.cache/standards/`, where vitest and Effect resolve from the project's install, and gives the copy to Stryker's vitest runner too, through a copy of a JSON Stryker config with `vitest.configFile` set, which `checks stryker-config` writes there. The config's modes set the runs of every property test, through Effect's `Arbitrary`: `fast` runs 10, `full` 1000 with `@vitest/coverage-v8`, and `mutation` 10 with seed 42, ending on the first failure. `mutation` is also vitest's default mode, the one Stryker's vitest runner starts it in. A test tagged `slow` (`{ tags: ["slow"] }`) runs only in `full`. `check.sh` runs vitest in `fast` at `step` and `full` at `release`, which also runs Stryker on `@stryker-mutator/vitest-runner`. The exceptions check reports a project's own `vitest.config.ts`, or else `vite.config.ts`, whose modes run fewer cases than the standard's as drift; a project without one runs the standard's.
