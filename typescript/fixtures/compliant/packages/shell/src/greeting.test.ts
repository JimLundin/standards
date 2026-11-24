import { ConfigProvider, Effect, FileSystem, Layer } from "effect";
import { describe, expect, it } from "@effect/vitest";
import { greeting } from "./greeting.ts";

const files = FileSystem.layerNoop({
  readFileString: (path) => Effect.succeed(path === "ada.json" ? '{"name":"Ada"}' : "{}"),
});
const config = ConfigProvider.layer(ConfigProvider.fromUnknown({ FIXTURE_GREETING: "ada.json" }));

describe("the shell's greeting", () => {
  it.effect("greets the name in the file the config names", () =>
    Effect.map(greeting, (text) => {
      expect(text).toBe("Hello, Ada");
    }).pipe(Effect.provide(Layer.merge(files, config))),
  );
});
