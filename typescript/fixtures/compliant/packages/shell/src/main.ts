import { NodeRuntime } from "@effect/platform-node";
import { greet } from "@fixture/core";
import { Config, Console, Effect } from "effect";

const name = Config.String("FIXTURE_NAME").pipe(Config.withDefault("shell"));

const program = Effect.flatMap(name, (value) =>
	Console.log(greet({ name: value })),
);

NodeRuntime.runMain(program);
