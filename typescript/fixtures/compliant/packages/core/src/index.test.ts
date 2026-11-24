import { describe, expect, it } from "@effect/vitest";
import { Schema } from "effect";
import { greet } from "./index.ts";

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
