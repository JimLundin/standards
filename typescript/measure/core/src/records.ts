import type { Entry } from "./entries.ts";
import type { Export } from "./api.ts";
import type { Measured } from "./decisions.ts";
import { Schema } from "effect";
import { problems } from "./api.ts";

// A line of the layer map of `checks typescript-layers`: a file's layer, its package's folder and its path.
const Placement = Schema.Struct({
  layer: Schema.Literals(["core", "shell", "ui"]),
  path: Schema.String,
  root: Schema.String,
});
type Placement = typeof Placement.Type;

const LayerMap = Schema.Array(Placement);

// The fields of each line of a layer map, for LayerMap to decode.
const fields = (text: string): ReadonlyArray<Readonly<Record<string, string | undefined>>> =>
  text
    .split(/\r?\n/u)
    .filter((line) => line !== "")
    .map((line) => {
      const [layer, root, path] = line.split("\t");
      return { layer, path, root };
    });

// The record of a measured function, in rust-decisions' format with its layer; its root is its package.
const functionRecord = (
  { layer, path, root }: Placement,
  { decisions, line, name }: Measured,
): string => JSON.stringify({ decisions, function: name, layer, line, path, root });

// The records of what a core export reaches that isn't data, at the line of its export.
const apiRecords = ({ layer, path, root }: Placement, found: Export): ReadonlyArray<string> =>
  problems(found).map((api) =>
    JSON.stringify({ api, export: found.name, layer, line: found.line, path, root }),
  );

// The record of an entry point a file calls, named by its call; its root is its package.
const entry = ({ layer, path, root }: Placement, { call, line }: Entry): string =>
  JSON.stringify({ entry: call, layer, line, path, root });

const failure = ({ layer, path, root }: Placement, error: string): string =>
  JSON.stringify({ error, layer, path, root });

export { LayerMap, Placement, apiRecords, entry, failure, fields, functionRecord };
