import type { Measured } from "./decisions.ts";
import { Schema } from "effect";

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
const record = ({ layer, path, root }: Placement, { decisions, line, name }: Measured): string =>
  JSON.stringify({ decisions, function: name, layer, line, path, root });

// The record of a file that couldn't be measured.
const failure = ({ layer, path, root }: Placement, error: string): string =>
  JSON.stringify({ error, layer, path, root });

export { LayerMap, Placement, failure, fields, record };
