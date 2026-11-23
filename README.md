# Standards

Shared tool configuration and checks for Python, Rust and TypeScript projects.

Each config file can be copied to its usual place in a project, and the scripts use a project's own copy when it has one. The repository can be copied as a whole, since the scripts only use paths relative to it. A project names the profiles it follows in its `project.toml` in the home, and finds this repository's checkout by its root commit like any other project.

## Running the checks

```bash
python/check.sh [commit|step|release] [--no-cache] [project]
rust/check.sh …
typescript/check.sh …
```

- `commit` runs the exceptions, format, lint, type and structure checks.
- `step`, the default, adds the tests.
- `release` adds mutation testing, thorough property tests, slow and ignored tests, coverage, duplication and volume.

The scripts' own tools live in `checks`, a uv project that depends on `ordered` and passes the Python standard itself, so every language's checks need uv.

## Tool versions

`tools.env` pins the version of every tool the checks run or fetch, one `NAME=version` per line so CI can read it too. `uvx` and `npx` fetch the pinned version. Before a run, each installed tool, such as uv, Node, nextest, sccache or the project's Stryker, is compared with its pin, and a mismatch fails at once with the command that installs the pinned version.

## Units and recorded passes

A tier runs as units, each a check over a scope:

- in Rust, the lint, `no_std` core, API, shell and test checks of each package, and the exceptions, format and release checks of the whole project;
- in Python and TypeScript, each check of the project;
- each suite in `checks.toml`.

A unit's key hashes the check, the git tree of the standards, the toolchain's version (`cargo -V` and `rustc -V`, `uv --version` or `node --version`), the pinned version of the tool the check runs, and the git blobs of the files it reads:

- A whole-project unit reads every file.
- A Rust package reads every file in its folder, Rust or not, such as its manifest and test fixtures; every file of its workspace dependencies, from `cargo metadata`; and every project file outside the packages and the docs (`*.md`, `docs/`, licences, `.github/`), such as `Cargo.lock`, the root `Cargo.toml` or `rust-toolchain.toml`.

So a test fixture reruns its package and the packages that depend on it, and a lockfile or root manifest change reruns every package.

A pass is recorded as a git note on `refs/notes/checks` whose annotated object name is the key, so one `git notes list` reads every pass. A unit whose key has a pass reports `passed (recorded)` without running. Failures are never recorded. The keys are taken again after a check, and a pass is recorded only if its key still matches. `--no-cache` runs every unit, and still records its passes.

`check.sh` fetches the notes from `origin` before a run, merges them by union (`git notes merge -s cat_sort_uniq`) and pushes them after; a project without `origin` keeps them local. The standards keep their own index of the project's files under the user's cache directory (`STANDARDS_CACHE` overrides it), so listing the files doesn't touch the project's index.

A Rust package check runs once over the whole workspace when any package's pass is missing: cargo then resolves features once and rebuilds only what changed, where selecting packages with `-p` would resolve their features apart from the workspace's and rebuild dependencies. nextest builds the workspace's tests and runs only the unproven packages' with a filterset. Each failure in the output is credited to a package: an error's location or a finding's path to the package whose directory holds it, cargo's `could not compile` to a package and its dependents, and a failed test to its package. The packages without a failure are recorded, and a failure outside every package records none.

## Suites

A project declares its own suites in `checks.toml`. Each `[[suite]]` has a `name`, a `command` run by bash from the project root, and `[[suite.when]]` entries of a `tier` with `paths` globs, in Rust `packages`, or neither. A suite is a unit at the lowest of those tiers and above, and reads the files its `paths` match and the inputs of its `packages`, or the whole project when an entry names neither.

## Exceptions

Exceptions live only in a project's `exceptions.toml`; suppression comments and weakened configs fail the checks. Each entry has a path glob, a rule and a reason; `exceptions.toml` at the root lists the rules.

## Rust

**Layers.** A package declares its layer in its `Cargo.toml` as `layer = "core"` or `layer = "shell"` under `[package.metadata.standards]`, and an undeclared package is core. Core libraries are the pure core, and binaries and shell packages are the imperative shell.

**`no_std` core.** The checks build each core library with all its features for `wasm32v1-none`, where `std` doesn't exist, so a core library must be `#![no_std]` and its dependencies must be too, whichever features are on. Its root declares `#![no_std]` unconditionally, or `#![cfg_attr(not(test), no_std)]`, and `extern crate std` appears only under `#[cfg(test)]`, so no target or feature hands the core `std` and its I/O; these take no exception.

**Plain values.** The same build lints the core libraries with the project's clippy config, which adds `Box`, `Rc`, `Arc` and their `Weak`s to its disallowed types: the core holds plain values, so a recursive type keeps its parts in a `Vec` and refers to them by index. A core file that needs one takes a `box` exception; the shell may use them freely.

**Data-only API.** A core library's public API takes only data: no trait objects, function pointers, `async`, or bounds other than the standard value traits (`Clone`, `Ord`, `Hash`, `Display`, `From` and the like), so the shell can't hand the core an effect through a port, a callback or an iterator. A file that needs one takes an `api` exception.

**Thin shell.** No function in a binary or a shell package may make more than 2 decisions, and once a project makes 20 decisions, the shell may make at most 25% of them. A decision is an `if`, a `match` of more than one arm, a match guard, a `for` or `while` loop, a `let … else` or a run of `&&` or `||`, written in the function, its closures or a macro's arguments; `?`, `.await` and macro expansions are not. `rust-decisions`, in `rust/measure`, counts them from the source; install it with `cargo install --locked --path rust/measure`. A file takes a `shell` exception for the first rule and `Cargo.toml` for the second. Mutation testing skips shell-only files.

**Lints.** A project without its own `[lints]` is linted with those of `rust/Cargo.fragment.toml`.

**Flaky tests.** A test that fails only under load takes a `flaky` exception naming the test or a glob of its nextest name. nextest retries just those once, the summary reports a pass on the retry as `flaky`, and retries in a project's own nextest config fail the checks.

**sccache.** `check.sh` sources `rust/build.sh`, and a shell can source it from a project root before plain cargo. Where sccache is installed, cargo compiles through it as `RUSTC_WRAPPER`, into a cache under `~/.cache/sccache` that every worktree shares, unlike a shared target dir, which is unsafe across worktrees. A `RUSTC_WRAPPER` the caller already set wins, and without sccache cargo builds as before. sccache can't cache incremental builds, proc-macros or binaries, so it saves most on dependencies, and a path inside the checkout, such as a build script's `OUT_DIR`, is part of the key, so another worktree misses on the crates that read one. Linking needs nothing: the toolchain links Linux hosts with its bundled `rust-lld`.

## Python

**Layers and purity.** An exhaustive import-linter layers contract puts the core at the bottom, so it imports nothing else of the app. The purity check holds the core to pure standard modules, no effectful builtins such as `open`, `input` or `eval`, and a public API that takes only data: no `Callable`, `Iterable`, `IO`, `type[...]`, `Protocol` or ABC of its own, and no `async`. A pure third-party package takes a `PUR001:<module>` exception.

**Ordered collections.** `python/ordered` is a small package of collections whose iteration order is part of their type: `OrderedCollection`, `OrderedSequence`, `OrderedSet` and `OrderedMapping` extend the collection ABCs with that promise, and `FrozenList`, `FrozenOrderedSet` and `FrozenOrderedDict` implement them, with set and merge operations that keep the left operand's order. Projects copy it or depend on it, and the core may import it.

**Immutability.** The immutability check makes `ordered` the vocabulary: no set literals, set comprehensions, `set()` or `frozenset()`, since they iterate in hash order; no `set`, `frozenset`, `AbstractSet` or `Collection` in annotations, since they promise no order; and `FrozenList` and `FrozenOrderedDict` in place of `tuple[T, ...]`, `frozendict` and `MappingProxyType`. Plain `Sequence`, `Mapping` and `Container` stay for inputs that don't depend on order.
