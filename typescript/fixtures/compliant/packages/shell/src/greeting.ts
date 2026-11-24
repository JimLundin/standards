import { Config, Effect, FileSystem, Schema } from "effect";
import { GreetingJson, greet } from "@fixture/core";

// The greeting of the JSON file that FIXTURE_GREETING names.
const greeting = Effect.gen(function* readGreeting() {
	const path = yield* Config.String("FIXTURE_GREETING");
	const fileSystem = yield* FileSystem.FileSystem;
	const text = yield* fileSystem.readFileString(path);
	const decoded = yield* Schema.decodeUnknownEffect(GreetingJson)(text);
	return greet(decoded);
});

export { greeting };
