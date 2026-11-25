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

const shell = "packages/shell";

const inShell = (path: string): Placed => ({ layer: "shell", path, root: shell });

// The entry records of a project of one file, written with `source`.
const measured = (placed: Placed, source: string): Effect.Effect<ReadonlyArray<string>, unknown> =>
  Effect.gen(function* write() {
    const fileSystem = yield* FileSystem.FileSystem;
    const path = yield* Path.Path;
    const project = yield* fileSystem.makeTempDirectoryScoped();
    const file = path.join(project, placed.path);
    const map = path.join(project, "layers.tsv");
    yield* fileSystem.makeDirectory(path.dirname(file), { recursive: true });
    yield* fileSystem.writeFileString(file, source);
    yield* fileSystem.writeFileString(map, `${placed.layer}\t${placed.root}\t${placed.path}\n`);
    const lines = yield* measure(project, map);
    return lines.filter((line) => line.startsWith('{"entry"'));
  }).pipe(Effect.scoped, Effect.provide(NodeServices.layer));

// The entry points of a file, each a call's name and line.
type Entered = readonly [string, number];

const entries = (
  placed: Placed,
  source: string,
  entered: ReadonlyArray<Entered>,
): Effect.Effect<void, unknown> =>
  Effect.map(measured(placed, source), (lines) => {
    expect(lines).toStrictEqual(
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

const pointFree = `import { NodeRuntime } from "@effect/platform-node";
import { runMain as run } from "@effect/platform-node/NodeRuntime";
import { Effect } from "effect";
Effect.void.pipe(NodeRuntime.runMain);
Effect.void.pipe(
  run,
);
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

  it.effect("records a runMain passed as a value, as to pipe", () =>
    entries(inShell(`${shell}/main.ts`), pointFree, [
      ["runMain", 4],
      ["runMain", 6],
    ]),
  );

  it.effect("records no call of the same name from elsewhere", () =>
    entries(inShell(`${shell}/main.ts`), lookalikes, []),
  );
});
