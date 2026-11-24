# Standards

Shared tool configuration and checks that hold Python, Rust and TypeScript projects to one design: a pure core and a thin imperative shell.

## Layers

**Core**:
The pure layer of a project: packages that take and return only data and perform no effects.
_Avoid_: domain, model, lib

**Shell**:
The imperative layer of a project: binaries and packages that perform effects and call the core. In TypeScript, the code that runs Effect.
_Avoid_: boundary, adapter, infrastructure

**Decision**:
A branch the code writes: an `if`, a ternary or a multi-arm `match`/`switch`, a loop, a run of `&&`/`||`/`??`, and, in TypeScript, a branching Effect combinator. The thin-shell rules count them.
