# TypeScript lints with Oxlint and formats with oxfmt

The TypeScript standard drops Biome. Oxlint lints with `@cloudflare/oxlint-config` plus every category except nursery, type-aware through `oxlint-tsgolint`, and oxfmt formats with its own defaults. Biome has no type-aware rules, and custom rules in Biome can only be GritQL patterns, which can't see scopes or types and can only be skipped all at once. Oxlint's JS plugins can use scope analysis, and its type-aware rules catch unsafe casts and floating promises.

## Consequences

- Neither Oxlint's config nor the CLI has an "all" switch that includes nursery. The standard lists the categories and turns off contradicting rules with reasons, as Ruff `ALL` and Clippy do.
- Oxlint can't forbid inline disable comments, so the suppressions check rejects `oxlint-disable` and `eslint-disable`.
- A config in TypeScript can't be read as data, so drift evaluates it in Node.
- oxfmt's default width is 100, while Python and Rust wrap at 80.
- JS plugins are alpha and see no types: a rule that needs types belongs in `typescript/measure`.
