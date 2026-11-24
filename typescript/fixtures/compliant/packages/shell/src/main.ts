import { Console, Effect } from "effect";
import { NodeRuntime, NodeServices } from "@effect/platform-node";
import { greeting } from "./greeting.ts";

NodeRuntime.runMain(
	greeting.pipe(
		Effect.flatMap(Console.log),
		Effect.provide(NodeServices.layer),
	),
);
