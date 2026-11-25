import { Greeting, greet } from "./index.ts";
import { describe, expect, it } from "@effect/vitest";
import { Schema } from "effect";

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
  it("is a name", () => {
    expect.hasAssertions();
    expect(Object.keys(Greeting.fields)).toStrictEqual(["name"]);
  });
});
