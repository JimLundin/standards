import { greet } from "@fixture/core";
import { Effect } from "effect";
import { Atom } from "effect/reactivity";
import { BrowserKeyValueStore } from "@effect/platform-browser";
import { KeyValueStore } from "effect/persistence";

const runtime = Atom.runtime(BrowserKeyValueStore.layerLocalStorage);

export const greeting = runtime.atom(
	Effect.gen(function* readGreeting() {
		const store = yield* KeyValueStore.KeyValueStore;
		const name = yield* store.get("name");
		return greet({ name: name ?? "ui" });
	}),
);
