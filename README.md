# Standards

Shared tool configuration and checks for Python, Rust and TypeScript projects.

Each config file can be copied to its usual place in a project, and the scripts use a project's own copy when it has one. The repository can be copied as a whole, since the scripts only use paths relative to it. A project names the profiles it follows in its `project.toml` in the home, and finds this repository's checkout by its root commit like any other project.

## Running the checks

```bash
python/check.sh [commit|step|release] [--no-cache|--verify|--affected] [project]
rust/check.sh …
typescript/check.sh …
```

- `commit` runs the exceptions, format, lint, type and structure checks.
- `step`, the default, adds the tests.
- `release` adds mutation testing, thorough property tests, slow and ignored tests with their coverage, one unit, duplication and volume.

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

`tools.env` pins the version of every tool the checks run or fetch, one `NAME=version` per line so CI can read it too. `uvx` and `npx` fetch the pinned version. Before a run, each installed tool, such as uv, Node, nextest, sccache, `rust-decisions`, `typescript-measure` or the project's Stryker, vitest and Effect, is compared with its pin, and a mismatch fails at once with the command that installs the pinned version. Python is the one uv resolves: `check.sh` sets `UV_PYTHON` to the `PYTHON` pin, so the standards' checks, a Python project's checks and its key use that interpreter whatever `python3` is on `PATH`, and a suite runs with it first on `PATH`.

## Units and recorded passes

A tier runs as units, each a check over a scope:

- in Rust, the lint, `no_std` core, API, shell and test checks of each package, and the exceptions, format, shell share and release checks of the whole project;
- in Python and TypeScript, each check of the project;
- each suite in `checks.toml`.

A unit's key hashes the check, the git tree of the standards, the toolchain's version (`cargo -V` and `rustc -V`, `uv --version` or `node --version`), the pinned version of the tool the check runs, and the git blobs of the files it reads:

- A whole-project unit reads every file.
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

Exceptions live only in a project's `exceptions.toml`; suppression comments and weakened configs fail the checks. Each entry has a path glob, a rule and a reason; `exceptions.toml` at the root lists the rules. A TypeScript lint exception names its rule `lint/<plugin>/<rule>`, as Oxlint prints it, such as `lint/typescript/no-floating-promises` or `lint/eslint/no-bitwise`; `checks oxlint-config` writes a config under `node_modules/.cache/standards/` that extends the project's or the standard's config and turns each such rule off for its path, anchored at the project root, and the lint unit runs Oxlint with it.

## Rust

**Layers.** A package declares its layer in its `Cargo.toml` as `layer = "core"` or `layer = "shell"` under `[package.metadata.standards]`, and an undeclared package is core. Core libraries are the pure core, and binaries and shell packages are the imperative shell.

**`no_std` core.** The checks build each core library with all its features for `wasm32v1-none`, where `std` doesn't exist, so a core library must be `#![no_std]` and its dependencies must be too, whichever features are on. Its root declares `#![no_std]` unconditionally, or `#![cfg_attr(not(test), no_std)]`, and `extern crate std` appears only under `#[cfg(test)]`, so no target or feature hands the core `std` and its I/O; these take no exception.

**Plain values.** The same build lints the core libraries with the project's clippy config, which adds `Box`, `Rc`, `Arc` and their `Weak`s to its disallowed types: the core holds plain values, so a recursive type keeps its parts in a `Vec` and refers to them by index. A core file that needs one takes a `box` exception; the shell may use them freely.

**Data-only API.** A core library's public API takes only data: no trait objects, function pointers, `async`, or bounds other than the standard value traits (`Clone`, `Ord`, `Hash`, `Display`, `From` and the like), so the shell can't hand the core an effect through a port, a callback or an iterator. A file that needs one takes an `api` exception.

**Thin shell.** No function in a binary or a shell package may make more than 2 decisions, and once a project makes 20 decisions, the shell may make at most 25% of them. A decision is an `if`, a `match` of more than one arm, a match guard, a `for` or `while` loop, a `let … else` or a run of `&&` or `||`, written in the function, its closures or a macro's arguments; `?`, `.await` and macro expansions are not. `rust-decisions`, in `rust/measure`, counts them from the source; install it with `cargo install --locked --path rust/measure`, and bump its version and `RUST_DECISIONS` in `tools.env` with every change to it. A file takes a `shell` exception for the first rule and `Cargo.toml` for the second. The second is the `shell-share` unit of the whole project, so a merge of two branches that each kept the share is checked again. Mutation testing skips shell-only files.

**Lints.** A project without its own `[lints]` is linted with those of `rust/Cargo.fragment.toml`.

**Flaky tests.** A test that fails only under load takes a `flaky` exception naming the test or a glob of its nextest name. nextest retries just those once, the summary reports a pass on the retry as `flaky`, and retries in a project's own nextest config fail the checks.

**sccache.** `check.sh` sources `rust/build.sh`, and a shell can source it from a project root before plain cargo. Where sccache is installed, cargo compiles through it as `RUSTC_WRAPPER`, whose server `build.sh` starts so a first build never waits on one, into a cache under `~/.cache/sccache` that every worktree shares, unlike a shared target dir, which is unsafe across worktrees. A `RUSTC_WRAPPER` the caller already set wins, and without sccache cargo builds as before. sccache can't cache incremental builds, proc-macros or binaries, so it saves most on dependencies, and a path inside the checkout, such as a build script's `OUT_DIR`, is part of the key, so another worktree misses on the crates that read one. Linking needs nothing: the toolchain links Linux hosts with its bundled `rust-lld`.

## Python

**Layers and purity.** An exhaustive import-linter layers contract puts the core at the bottom, so it imports nothing else of the app. The purity check holds the core to pure standard modules, no effectful builtins such as `open`, `input` or `eval`, and a public API that takes only data: no `Callable`, `Iterable`, `IO`, `type[...]`, `Protocol` or ABC of its own, and no `async`. A pure third-party package takes a `PUR001:<module>` exception.

**Ordered collections.** `python/ordered` is a small package of collections whose iteration order is part of their type: `OrderedCollection`, `OrderedSequence`, `OrderedSet` and `OrderedMapping` extend the collection ABCs with that promise, and `FrozenList`, `FrozenOrderedSet` and `FrozenOrderedDict` implement them, with set and merge operations that keep the left operand's order. Projects copy it or depend on it, and the core may import it.

**Immutability.** The immutability check makes `ordered` the vocabulary: no set literals, set comprehensions, `set()` or `frozenset()`, since they iterate in hash order; no `set`, `frozenset`, `AbstractSet` or `Collection` in annotations, since they promise no order; and `FrozenList` and `FrozenOrderedDict` in place of `tuple[T, ...]`, `frozendict` and `MappingProxyType`. Plain `Sequence`, `Mapping` and `Container` stay for inputs that don't depend on order.

## TypeScript

**Layers and contracts.** A workspace package declares its layer in its `package.json` as `"standards": { "layer": "core" }`, `"shell"` or `"ui"`, and an undeclared package is core. A file belongs to its nearest package, and a file outside every package to the project root's. `checks typescript-layers <files>` prints the layer map: a `layer`, `package` and `file` line per file, separated by tabs, with `.` for the root package; any other layer name fails it, and fails `lint`. The lint unit adds a `no-restricted-imports` override per package of the map, for its folder without the packages nested in it and without tests and tool configs. The core imports only core packages, relative paths, Effect's pure data modules (`Schema`, `Data`, `Option`, `Result`, `Array`, `Order`, `Match`, `Equal`, `Hash`, `String`, `Number`, `Record`, `Struct`, and `pipe` and `flow` of `Function`) and the definitions of `effect/http-api` and `effect/rpc`, not their clients or servers; `HashMap` and `HashSet`, which iterate in hash order, are banned. Any other module a core file needs takes a `purity:<module>` exception, which allows the module and its subpaths in that file. The shell and the UI import the core and never each other: they meet only through **contracts** in core, the Schemas and HTTP API or RPC group definitions of what crosses between them.

**Lint and format.** oxfmt formats every tracked file it supports, with the project's `.oxfmtrc.json` or else the standard's `typescript/.oxfmtrc.json`, and sorts `package.json`. Oxlint lints with the project's `oxlint.config.ts`, which imports the standard's as `#standards/oxlint` and extends it, or else with the standard's, which extends `@cloudflare/oxlint-config`. Its rules are type-aware through `oxlint-tsgolint` where the project has a `tsconfig.json`. `check.sh` installs Oxlint, `oxlint-tsgolint` and the cloudflare config at their pins into its cache with `npm ci`, from `typescript/oxlint-install/package-lock.json`, which pins their own dependencies. A project merges `typescript/package.fragment.json` into its `package.json`; its `check` script runs `tsc && oxlint && oxfmt --check`, a quick local pass that `check.sh` stands in for, since only `check.sh` maps `#standards/oxlint`.

**Custom rules.** The standard's own lint rules are the Oxlint JS plugin `standards`, in `typescript/oxlint-plugins/`: one module per rule in `rules/`, named for it, and `index.ts`, which lists them. Node loads its `.ts` files by type stripping, and `oxlint.config.ts` loads it from beside itself and turns every rule it lists on, so a new rule is a module and an entry in the index. `no-module-state` reports a mutable binding at module scope and a module-level mutable collection; `readonly-members` a class property or type member without `readonly`; `no-plain-class` a class unless it extends `Schema.Class`, `Schema.TaggedClass`, `Schema.TaggedError`, a `Data` class or a `Context` service, resolved through its import from `effect`; `readonly-types` a mutable array, `Map` or `Set` type; `no-throw` a `throw` statement, and `no-try` a `try` statement. Each rule's vitest test runs the pinned Oxlint with only it on over example files, and the package's `test` unit runs them at `step`.

**Effect-only code.** By ADR 0004 every layer, core, shell and UI alike, is held to Effect's terms, each ban by one rule, native where Oxlint has one. `oxc/no-async-await` bans `async` and `await`, `promise/avoid-new` `new Promise`, and `no-restricted-properties` `.then`, so `Effect.tryPromise` is the one bridge to a Promise library. `standards/no-throw` and `standards/no-try` ban `throw` and `try`, so an error is a `Data.TaggedError` in an Effect's type. `no-restricted-properties` bans `JSON.parse`, so external data enters through `Schema.decodeUnknown*`. Time, randomness and logging come from Effect's `Clock`, `Random` and `Effect.log`: `no-restricted-globals` bans `Date`, `performance` and `crypto`, `no-restricted-properties` `Math.random`, and `no-console` `console`. A banned global read off `globalThis`, such as `globalThis.fetch`, is banned too by `no-restricted-properties`, and one read off `window` or `self` by `unicorn/prefer-global-this`.

**UI.** By ADR 0002 every effect of a `ui` package runs in an atom of `effect/reactivity`, over the services of `@effect/platform-browser`, and its components only read atoms, as with `useAtomValue` of `@effect/atom-react`; `useState` stays for transient view state. Each `ui` package's import override also bans `useEffect` and `useLayoutEffect` of `react`, and a second override bans the globals `window`, `document` and `localStorage`, and the same read off `globalThis`, beside the bans of every layer, which it extends, since an override replaces a rule's options. The app's entry point, which mounts it with `createRoot` on the document, takes a `lint/eslint/no-restricted-globals` exception.

**The measure tool.** `typescript-measure`, in `typescript/measure`, reads a project's source with TypeScript 7's own API (`typescript/unstable/sync` and `typescript/unstable/ast` of the pinned TypeScript) and, given the project and a file of the layer map from `checks typescript-layers`, prints a JSON record per function in `rust-decisions`' format, with the package's folder as its `root` and the file's `layer`, or a record with an `error` for a listed file it can't read. A decision is an `if`, a ternary, a `switch` of more than one case, a `for`, `while` or `do` loop, a run of `&&`, `||` or `??`, including a JSX conditional, or a call of a branching combinator by its name: `Effect.if`, `Effect.when`, `Match.when`, `Match.tag`, `Effect.catchTag`, `Effect.catchTags`, `Option.match` or `Result.match`; a `.map` makes none. A function's closures count in it, while a function declaration and a class's member are measured on their own, and so is each top-level declaration; a module's other top-level statements are the function `(module)`, recorded when they make a decision. The tool follows the standard itself, an Effect shell over the pure core package `typescript/measure/core`. Install it with `npm ci --prefix typescript/measure && npm install -g typescript/measure`, which links the checkout, and bump its version in `package.json` and `TS_MEASURE` in `tools.env` with every change to it.

**Types.** The `types` unit runs `effect-tsgo tsc` of `@effect/tsgo` (pinned as `EFFECT_TSGO`) at the pinned TypeScript, over a tsconfig that extends the project's and the standard's and turns the Effect language service on, so Effect's own errors, such as `floatingEffect` for an Effect that is created and never yielded or run, fail it like any type error; its warnings and suggestions are printed but don't fail it. `tsconfig.base.json` turns the same plugin on for editors.

**Tests.** Tests run on vitest with `it` from `@effect/vitest`, the one test function: `it.effect` for an Effect, `it.prop` for a property over Schemas or Arbitraries. A project copies `vitest.config.ts` and `vitest.setup.ts` to its root. The config's modes set the runs of every property test, through Effect's `Arbitrary`: `fast` runs 10, `full` 1000 with `@vitest/coverage-v8`, and `mutation` 10 with seed 42, ending on the first failure. `mutation` is also vitest's default mode, the one Stryker's vitest runner starts it in. A test tagged `slow` (`{ tags: ["slow"] }`) runs only in `full`. `check.sh` runs vitest in `fast` at `step` and `full` at `release`, which also runs Stryker on `@stryker-mutator/vitest-runner`. The exceptions check reports a project `vitest.config.ts` whose modes run fewer cases than the standard's as drift.
