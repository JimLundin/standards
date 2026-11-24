import { Effect, Layer } from "effect";
import { describe, expect, it } from "@effect/vitest";
import { greeting, runtime } from "./greeting.ts";
import { AtomRegistry } from "effect/reactivity";
import { Greeting } from "@fixture/core";
import { KeyValueStore } from "effect/persistence";

const stored = Layer.effect(
  KeyValueStore.KeyValueStore,
  Effect.tap(KeyValueStore.KeyValueStore, (store) =>
    KeyValueStore.toSchemaStore(store, Greeting).set("greeting", {
      name: "Ada",
    }),
  ),
).pipe(Layer.provide(KeyValueStore.layerMemory), Layer.orDie);

describe("the UI's greeting", () => {
  it.effect("greets the stored name", () =>
    Effect.map(
      AtomRegistry.getResult(
        AtomRegistry.make({ initialValues: [[runtime.layer, stored]] }),
        greeting,
      ),
      (text) => {
        expect(text).toBe("Hello, Ada");
      },
    ),
  );

  it.effect("greets the UI when no name is stored", () =>
    Effect.map(
      AtomRegistry.getResult(
        AtomRegistry.make({
          initialValues: [[runtime.layer, KeyValueStore.layerMemory]],
        }),
        greeting,
      ),
      (text) => {
        expect(text).toBe("Hello, UI");
      },
    ),
  );
});
