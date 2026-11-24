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

**UI**:
The browser layer of a TypeScript project: React packages that render views and run their effects in atoms. Like the shell, it calls the core and the core never calls it.
_Avoid_: frontend, client, view layer

**Contract**:
A core definition both the shell and the UI build on: the Schemas and `HttpApi` or `Rpc` group definitions of what crosses between them.
_Avoid_: interface, DTO, API types

**View model**:
The data a core function computes for a component to render, so that the component holds no logic of its own.
_Avoid_: presenter, props mapper
