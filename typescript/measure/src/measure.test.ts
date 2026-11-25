import { Effect, FileSystem, Path, Schema } from "effect";
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
export const oneCase = (a: { readonly kind: number }): number => {
  switch (a.kind) {
    default:
      return 1;
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
export const unparenthesized = (a: boolean, b: boolean, c: boolean): boolean => a && b || c;
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

const aliased = `import * as E from "effect/Effect";
import { when } from "effect/Match";
import { match as matched } from "effect/Option";
import { Result as R } from "effect";
export const program = E.if(true, { onTrue: () => E.void, onFalse: () => E.void });
export const matcher = when({ _tag: "A" }, () => 1);
export const chosen = matched({ onNone: () => 0, onSome: () => 1 });
export const settled = R.match(R.succeed(1), { onFailure: () => 0, onSuccess: () => 1 });
export const passed = E.map(E.void, E.when);
`;

const imitations = `import { Effect as Local } from "./effect.ts";
import { when as whenever } from "effect/Match";
const Option = { match: (a: number): number => a };
const when = (a: number): number => a;
export const local = Local.if(true, {});
export const own = Option.match(1);
export const mine = when(1);
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

const named = `export class Counter { constructor(start: boolean) { if (start) {} } }
export const { picked } = { picked: (a: boolean): number => (a ? 1 : 2) };
export function
late(a: boolean): number { return a ? 1 : 2; }
export default (a: boolean): number => (a ? 1 : 2);
`;

const statements = `[1].map((x) => { const kept = x; return kept ? kept : 0; });
[{ get value() { const inner = 1; return inner || 0; } }];
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
      ["unparenthesized", 35, 2],
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

describe("the combinators of a file's imports", () => {
  it.effect("counts a combinator imported under another name, or by its own name", () =>
    counts(inShell(`${shell}/src/aliased.ts`), aliased, [
      ["program", 5, 1],
      ["matcher", 6, 1],
      ["chosen", 7, 1],
      ["settled", 8, 1],
      ["passed", 9, 0],
    ]),
  );

  it.effect("counts no call spelled like a combinator that isn't imported from Effect", () =>
    counts(inShell(`${shell}/src/imitations.ts`), imitations, [
      ["Option", 3, 0],
      ["when", 4, 0],
      ["local", 5, 0],
      ["own", 6, 0],
      ["mine", 7, 0],
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

  it.effect(
    "names a constructor, a default export and a function without a name, at its name's line",
    () =>
      counts(inShell(`${shell}/src/named.ts`), named, [
        ["Counter", 1, 0],
        ["constructor", 1, 1],
        ["(anonymous)", 2, 1],
        ["late", 4, 1],
        ["default", 5, 1],
      ]),
  );
});

describe("the module's own statements", () => {
  it.effect("counts the decisions of a module's own statements as the module's", () =>
    counts(inShell(`${shell}/main.ts`), main, [["(module)", 1, 1]]),
  );

  it.effect("counts the declarations in a module statement's closures as the module's", () =>
    counts(inShell(`${shell}/src/statements.ts`), statements, [["(module)", 1, 2]]),
  );
});

const web = { layer: "web", path: `${shell}/src/web.ts`, root: shell } as const;

describe("the layer map", () => {
  it.effect("rejects a layer other than core, shell and ui", () =>
    Effect.map(Effect.flip(measured(web, "export {};\n")), (failure) => {
      expect(Schema.isSchemaError(failure)).toBe(true);
    }),
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
