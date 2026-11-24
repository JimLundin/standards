import { Effect, FileSystem, Path } from "effect";
import { describe, expect, it } from "@effect/vitest";
import { NodeServices } from "@effect/platform-node";
import { measure } from "./measure.ts";

// A file of the layer map, with its source.
interface Written {
  readonly layer: string;
  readonly root: string;
  readonly path: string;
  readonly source: string;
}

// An export's name, line and what it reaches that isn't data.
type Reported = readonly [string, number, string];

const core = "packages/core";

const inCore = (name: string, source: string): Written => ({
  layer: "core",
  path: `${core}/src/${name}.ts`,
  root: core,
  source,
});

// The api records of a project of the files `written`, which resolves effect from this package's node_modules.
const judged = (written: ReadonlyArray<Written>): Effect.Effect<ReadonlyArray<string>, unknown> =>
  Effect.gen(function* write() {
    const fileSystem = yield* FileSystem.FileSystem;
    const path = yield* Path.Path;
    const project = yield* fileSystem.makeTempDirectoryScoped();
    yield* fileSystem.symlink(path.resolve("node_modules"), path.join(project, "node_modules"));
    yield* fileSystem.writeFileString(
      path.join(project, "tsconfig.json"),
      '{ "compilerOptions": { "module": "nodenext", "noEmit": true } }\n',
    );
    yield* Effect.forEach(written, (file) => {
      const target = path.join(project, file.path);
      return fileSystem
        .makeDirectory(path.dirname(target), { recursive: true })
        .pipe(Effect.andThen(fileSystem.writeFileString(target, file.source)));
    });
    const map = path.join(project, "layers.tsv");
    yield* fileSystem.writeFileString(
      map,
      written.map(({ layer, path: file, root }) => `${layer}\t${root}\t${file}\n`).join(""),
    );
    const lines = yield* measure(project, map);
    return lines.filter((line) => line.startsWith('{"api":'));
  }).pipe(Effect.scoped, Effect.provide(NodeServices.layer));

// That the project of the one file `written` reports what each export of `reported` reaches.
const reports = (
  written: Written,
  reported: ReadonlyArray<Reported>,
): Effect.Effect<void, unknown> =>
  Effect.map(judged([written]), (lines) => {
    const { layer, path, root } = written;
    expect(lines).toStrictEqual(
      reported.map(([name, line, api]) =>
        JSON.stringify({ api, export: name, layer, line, path, root }),
      ),
    );
  });

const effectful = inCore(
  "effectful",
  `import { Effect } from "effect";
export const callback = (f: (n: number) => number): number => f(1);
export const promised = (): Promise<number> => Promise.resolve(1);
export const effect: Effect.Effect<number> = Effect.succeed(1);
export const iterated = (xs: Iterable<number>): number => [...xs].length;
export class Runner {
  run(): number {
    return 1;
  }
}
`,
);

const hidden = inCore(
  "hidden",
  `import { Effect } from "effect";
type Later = () => number;
interface Job {
  readonly work: Effect.Effect<number>;
}
interface Box<A> {
  readonly value: A;
}
export const aliased = (later: Later): number => later();
export const nested = (job: Job): Job => job;
export const generic = (box: Box<() => void>): number => 1;
export type Wrapped = Box<Promise<number>>;
export const listed: ReadonlyArray<Effect.Effect<number>> = [];
export { nested as again };
class Runner {
  run(): number {
    return 1;
  }
}
type Ran = Runner;
export const ran = (runner: Ran): number => runner.run();
`,
);

const services = inCore(
  "services",
  `import { Context, Layer, Stream } from "effect";
export const stream: Stream.Stream<number> = Stream.empty;
export const layer: Layer.Layer<never> = Layer.empty;
export class Clock extends Context.Service<Clock, { readonly now: number }>()("Clock") {}
export const pulled = (xs: AsyncIterable<number>): number => 1;
`,
);

const data = inCore(
  "data",
  `import { Data, Option, Schema } from "effect";
export class Person extends Schema.Class<Person>("Person")({ name: Schema.String }) {
  greet(): string {
    return this.name;
  }
}
export class Missing extends Data.TaggedError("Missing")<{ readonly id: string }> {}
export const maybe = (name: string): Option.Option<string> => Option.some(name);
export const indexed: ReadonlyMap<string, ReadonlyArray<number>> = new Map();
export const Greeting = Schema.Struct({ name: Schema.String });
export type Greeting = typeof Greeting.Type;
export const pair: readonly [number, string] = [1, "a"];
export const named: Readonly<Record<string, number>> = {};
export const identity = <A>(a: A): A => a;
export const greeted = (person: Person, missing: Missing): string => person.greet() + missing.id;
export type Shade = "light" | "dark";
export enum Colour {
  Red,
}
export interface Tree {
  readonly children: ReadonlyArray<Tree>;
  readonly parent: Tree | undefined;
}
export class Chain {
  readonly next: Chain | undefined = undefined;
}
`,
);

describe("what a core export reaches that isn't data", () => {
  it.effect(
    "reports an export that takes a callback, returns a Promise or an Effect, takes an Iterable or is a class with methods",
    () =>
      reports(effectful, [
        ["callback", 2, "reaches a function type, `(n: number) => number`"],
        ["promised", 3, "reaches `Promise`"],
        ["effect", 4, "reaches `Effect.Effect`"],
        ["iterated", 5, "reaches `Iterable`"],
        ["Runner", 6, "is a class with methods, `run`"],
      ]),
  );

  it.effect(
    "reports at the export a function or an Effect reached through an alias, an interface or a generic argument",
    () =>
      reports(hidden, [
        ["aliased", 9, "reaches a function type, `Later`"],
        ["nested", 10, "reaches `Effect.Effect`"],
        ["generic", 11, "reaches a function type, `() => void`"],
        ["Wrapped", 12, "reaches `Promise`"],
        ["listed", 13, "reaches `Effect.Effect`"],
        ["again", 14, "reaches `Effect.Effect`"],
        ["ran", 21, "reaches a class with methods, `run`"],
      ]),
  );

  it.effect("reports a Stream, a Layer, a Context service and an async iterable", () =>
    reports(services, [
      ["stream", 2, "reaches `Stream.Stream`"],
      ["layer", 3, "reaches `Layer.Layer`"],
      ["Clock", 4, "reaches `Context.ServiceClass`"],
      ["pulled", 5, "reaches `AsyncIterable`"],
    ]),
  );
});

describe("what a core export may reach", () => {
  it.effect(
    "passes Schema and Data classes, Option, ReadonlyMap, Schemas, tuples, records, generics and recursive data",
    () => reports(data, []),
  );

  it.effect("judges only the core's files", () =>
    reports({ ...effectful, layer: "shell", path: "packages/shell/src/effectful.ts" }, []),
  );
});
