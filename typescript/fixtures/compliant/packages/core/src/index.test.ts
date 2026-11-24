import { Effect, Exit, Schema } from "effect";
import { GreetingJson, greet } from "./index.ts";
import { describe, expect, it } from "@effect/vitest";

describe(greet, () => {
  it("greets by name", () => {
    expect.hasAssertions();
    expect(greet({ name: "Ada" })).toBe("Hello, Ada");
  });

  it.prop(
    "greets every name",
    { name: Schema.String },
    ({ name }) => greet({ name }) === `Hello, ${name}`,
  );
});

describe("the greeting contract", () => {
  it.effect("decodes a greeting from JSON", () =>
    Effect.map(Schema.decodeUnknownEffect(GreetingJson)('{"name":"Ada"}'), (greeting) => {
      expect(greeting).toStrictEqual({ name: "Ada" });
    }),
  );

  it.effect("rejects a greeting without a name", () =>
    Effect.map(Effect.exit(Schema.decodeUnknownEffect(GreetingJson)("{}")), (exit) => {
      expect(Exit.isFailure(exit)).toBe(true);
    }),
  );
});
