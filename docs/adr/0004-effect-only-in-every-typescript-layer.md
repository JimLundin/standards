# Every TypeScript layer is held to Effect's terms, with no Node

The TypeScript standard bans Node imports, `async`/`await`, Promises, `throw`, `try`/`catch`, `JSON.parse`, ambient time, randomness and logging, and plain classes in every layer: core, shell and UI alike. It doesn't ban them only in the shell. The shell does I/O through Effect's platform services and the UI runs its effects in atoms. So no layer has a legitimate use for any of these, and one rule set with no per-layer bans leaves no gap for an exception to slip through.

## Consequences

- `@effect/platform-node` is a package, not a `node:*` import, so a Node shell is still possible, but only through Effect.
- Classes are allowed only when they extend an Effect constructor: `Schema.Class`, `Schema.TaggedError`, the `Data` classes and `Context` services.
- Layers still differ in what they may import, and in the core's data-only API and the shell's decision limits.
