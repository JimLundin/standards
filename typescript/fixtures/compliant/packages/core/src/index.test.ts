import { greet } from "./index.ts";
import { strictEqual } from "node:assert/strict";
import { test } from "node:test";

test("greets by name", () => {
	strictEqual(greet({ name: "Ada" }), "Hello, Ada");
});
