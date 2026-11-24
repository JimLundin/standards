#!/usr/bin/env node
import { Argument, Command } from "effect/cli";
import { Console, Effect } from "effect";
import { NodeRuntime, NodeServices } from "@effect/platform-node";
import manifest from "./package.json" with { type: "json" };
import { measure } from "./src/measure.ts";

const command = Command.make(
  "typescript-measure",
  {
    directory: Argument.Directory("project", { mustExist: true }),
    layers: Argument.File("layers", { mustExist: true }),
  },
  ({ directory, layers }) =>
    Effect.flatMap(measure(directory, layers), (lines) => Console.log(lines.join("\n"))),
);

NodeRuntime.runMain(
  Command.run(command, { version: manifest.version }).pipe(Effect.provide(NodeServices.layer)),
);
