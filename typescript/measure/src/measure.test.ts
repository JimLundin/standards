import { Effect, FileSystem, Path } from "effect";
import { describe, expect, it } from "@effect/vitest";
import { NodeServices } from "@effect/platform-node";
import { measure } from "./measure.ts";

// A file of the layer map: its layer, its package's folder and its path.
interface Placed {
  readonly layer: string;
  readonly root: string;
  readonly path: string;
}

// A function's name, line and decisions.
type Counted = readonly [string, number, number];

const shell = "packages/shell";

// The record lines of a project of one file, written with `source` unless it's undefined.
const measured = (placed: Placed, source?: string): Effect.Effect<ReadonlyArray<string>, unknown> =>
  Effect.gen(function* write() {
    const fileSystem = yield* FileSystem.FileSystem;
    const path = yield* Path.Path;
    const project = yield* fileSystem.makeTempDirectoryScoped();
    const file = path.join(project, placed.path);
    const map = path.join(project, "layers.tsv");
    yield* fileSystem.makeDirectory(path.dirname(file), { recursive: true });
    yield* source === undefined ? Effect.void : fileSystem.writeFileString(file, source);
    yield* fileSystem.writeFileString(map, `${placed.layer}\t${placed.root}\t${placed.path}\n`);
    return yield* measure(project, map);
  }).pipe(Effect.scoped, Effect.provide(NodeServices.layer));

const records = (placed: Placed, counted: ReadonlyArray<Counted>): ReadonlyArray<string> =>
  counted.map(([name, line, decisions]) =>
    JSON.stringify({
      decisions,
      function: name,
      layer: placed.layer,
      line,
      path: placed.path,
      root: placed.root,
    }),
  );

const ENTRY = '{"entry"';

const counts = (
  placed: Placed,
  source: string,
  counted: ReadonlyArray<Counted>,
): Effect.Effect<void, unknown> =>
  Effect.map(measured(placed, source), (lines) => {
    expect(lines.filter((line) => !line.startsWith(ENTRY))).toStrictEqual(records(placed, counted));
  });

const written = `export const ifs = (a: boolean): number => {
  if (a) {
    return 1;
  } else if (!a) {
    return 2;
  }
  return 3;
};
export const ternary = (a: boolean): number => (a ? 1 : 2);
export const cases = (a: number): number => {
  switch (a) {
    case 1:
      return 1;
    default:
      return 2;
  }
};
export const oneCase = (a: number): number => {
  switch (a) {
    default:
      return a;
  }
};
export const loops = (xs: ReadonlyArray<number>): void => {
  for (const x of xs) {}
  for (let i = 0; i < 1; i++) {}
  for (const k in xs) {}
  while (xs) {}
  do {} while (xs);
};
export const runs = (a: boolean, b: boolean, c: boolean): boolean => a && b && c;
export const mixed = (a: boolean, b: boolean, c: boolean): boolean => (a && b) || c;
export const coalesced = (a?: number, b?: number): number => a ?? b ?? 0;
export const bitwise = (a: number, b: number): boolean => (a & b) === (a | b);
`;

const closures = `export const mapped = (xs: ReadonlyArray<number>): ReadonlyArray<number> => xs.map((x) => x + 1);
export const filtered = (xs: ReadonlyArray<number>): ReadonlyArray<number> =>
  xs.filter((x) => (x > 1 ? true : x < 0)).map((x) => ({ get y() { return x || 1; } }).y);
export function declared(a: boolean): boolean {
  function inner(): void {
    if (a) {}
  }
  inner();
  return a || false;
}
`;

const combinators = `import { Effect, Match, Option, Result } from "effect";
export const program = Effect.gen(function* run() {
  yield* Effect.if(true, { onTrue: () => Effect.void, onFalse: () => Effect.void });
  yield* Effect.when(Effect.void, Effect.succeed(true));
  yield* Effect.catchTag(Effect.void, "A", () => Effect.void);
  yield* Effect.catchTags(Effect.void, { A: () => Effect.void });
  yield* Effect.map(Effect.void, () => 1);
  return Option.match(Option.none(), { onNone: () => 0, onSome: () => 1 })
    + Result.match(Result.succeed(1), { onFailure: () => 0, onSuccess: () => 1 });
});
export const matcher = Match.type<{ readonly _tag: "A" }>().pipe(
  Match.when({ _tag: "A" }, () => 1),
  Match.tag("A", () => 1),
  Match.orElse(() => 0),
);
`;

const view = `import { Option } from "effect";
export const View = ({ a, b }: { readonly a: boolean; readonly b: Option.Option<string> }) => (
  <div>
    {a ? <p /> : <span />}
    {a && <i />}
    {Option.match(b, { onNone: () => <b />, onSome: (s) => <s>{s}</s> })}
  </div>
);
`;

const classes = `import { Schema } from "effect";
export class Greeter extends Schema.Class<Greeter>("Greeter")({ name: Schema.String }) {
  get greeting(): string {
    return this.name ? "hi" : "";
  }
}
`;

const main = `import { NodeRuntime } from "@effect/platform-node";
import { program } from "./src/combinators.ts";
NodeRuntime.runMain(program.pipe((self) => (self ? self : self)));
`;

const inShell = (path: string): Placed => ({ layer: "shell", path, root: shell });

describe("the decisions of a function", () => {
  it.effect("counts each kind of written decision once, and a switch of one case none", () =>
    counts(inShell(`${shell}/src/kinds.ts`), written, [
      ["ifs", 1, 2],
      ["ternary", 9, 1],
      ["cases", 10, 1],
      ["oneCase", 18, 0],
      ["loops", 24, 5],
      ["runs", 31, 1],
      ["mixed", 32, 2],
      ["coalesced", 33, 1],
      ["bitwise", 34, 0],
    ]),
  );

  it.effect(
    "counts closures in their function, a declared function on its own, and a map none",
    () =>
      counts(inShell(`${shell}/src/closures.ts`), closures, [
        ["mapped", 1, 0],
        ["filtered", 2, 2],
        ["declared", 4, 1],
        ["inner", 5, 1],
      ]),
  );

  it.effect("counts the branching combinators, and no other call", () =>
    counts(inShell(`${shell}/src/combinators.ts`), combinators, [
      ["program", 2, 6],
      ["matcher", 11, 2],
    ]),
  );
});

describe("the functions of a file", () => {
  it.effect("counts a component's JSX conditionals, in its layer", () =>
    counts({ layer: "ui", path: "packages/ui/src/view.tsx", root: "packages/ui" }, view, [
      ["View", 2, 3],
    ]),
  );

  it.effect("measures a class's members on their own", () =>
    counts(
      { layer: "core", path: "packages/core/src/greeter.ts", root: "packages/core" },
      classes,
      [
        ["Greeter", 2, 0],
        ["greeting", 3, 1],
      ],
    ),
  );

  it.effect("counts the decisions of a module's own statements as the module's", () =>
    counts(inShell(`${shell}/main.ts`), main, [["(module)", 1, 1]]),
  );

  it.effect("reports a file it can't read", () => {
    const placed = inShell(`${shell}/src/gone.ts`);
    return Effect.map(measured(placed), (lines) => {
      expect(lines).toStrictEqual([
        JSON.stringify({
          error: "not in the project",
          layer: "shell",
          path: placed.path,
          root: shell,
        }),
      ]);
    });
  });
});

// The entry points of a file, each a call's name and line.
type Entered = readonly [string, number];

const entries = (
  placed: Placed,
  source: string,
  entered: ReadonlyArray<Entered>,
): Effect.Effect<void, unknown> =>
  Effect.map(measured(placed, source), (lines) => {
    expect(lines.filter((line) => line.startsWith(ENTRY))).toStrictEqual(
      entered.map(([entry, line]) =>
        JSON.stringify({
          entry,
          layer: placed.layer,
          line,
          path: placed.path,
          root: placed.root,
        }),
      ),
    );
  });

const runtimes = `import { NodeRuntime } from "@effect/platform-node";
import { runMain as run } from "@effect/platform-node/NodeRuntime";
import * as Runtime from "@effect/platform-node/NodeRuntime";
import { Effect } from "effect";
NodeRuntime.runMain(Effect.void);
run(Effect.void);
Runtime.runMain(Effect.void);
`;

const roots = `import * as Client from "react-dom/client";
import Dom from "react-dom/client";
import { createRoot } from "react-dom/client";
import { RegistryProvider } from "@effect/atom-react";
createRoot(document.body).render(<RegistryProvider />);
export const mount = (element: HTMLElement): void => {
  Client.createRoot(element).render(<RegistryProvider />);
  Dom.createRoot(element);
};
`;

const lookalikes = `import { NodeRuntime } from "./runtime.ts";
import { runMain } from "@effect/platform-node";
import { hydrateRoot } from "react-dom/client";
const createRoot = (element: unknown): unknown => element;
NodeRuntime.runMain(1);
runMain(1);
createRoot(1);
hydrateRoot(document.body, null);
`;

describe("the entry points of a file", () => {
  it.effect("records each runMain imported from @effect/platform-node, however it's imported", () =>
    entries(inShell(`${shell}/main.ts`), runtimes, [
      ["runMain", 5],
      ["runMain", 6],
      ["runMain", 7],
    ]),
  );

  it.effect("records each createRoot imported from react-dom/client, in its layer", () =>
    entries({ layer: "ui", path: "packages/ui/src/main.tsx", root: "packages/ui" }, roots, [
      ["createRoot", 5],
      ["createRoot", 7],
      ["createRoot", 8],
    ]),
  );

  it.effect("records no call of the same name from elsewhere", () =>
    entries(inShell(`${shell}/main.ts`), lookalikes, []),
  );
});
