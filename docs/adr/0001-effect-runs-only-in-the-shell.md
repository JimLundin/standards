# Effect runs only in the TypeScript shell

The TypeScript standard makes Effect the framework of the shell, but the core stays plain data and pure functions, as in Rust and Python: it may use Effect's pure data modules (`Schema`, `Data`, `Option`, `Result`, `Array`, `Order`, `Match`) and never `Effect`, `Layer`, `Context` or a service.

## Options rejected

- A core that returns `Effect<A, E, never>`: `Effect.sync` would carry side effects into the core unseen.
- A core that requires services through `R`: a service is the port the other standards forbid the core to take.
