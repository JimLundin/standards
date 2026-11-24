import { Effect, Option } from "effect";
import { Greeting, greet } from "@fixture/core";
import { Atom } from "effect/reactivity";
import { BrowserKeyValueStore } from "@effect/platform-browser";
import { KeyValueStore } from "effect/persistence";

const runtime = Atom.runtime(BrowserKeyValueStore.layerLocalStorage);

// The greeting stored under "greeting", or one for the UI.
const greeting = runtime.atom(
	Effect.gen(function* readGreeting() {
		const store = yield* KeyValueStore.KeyValueStore;
		const stored = yield* KeyValueStore.toSchemaStore(store, Greeting).get(
			"greeting",
		);
		return greet(Option.getOrElse(stored, () => ({ name: "UI" })));
	}),
);

export { greeting, runtime };
