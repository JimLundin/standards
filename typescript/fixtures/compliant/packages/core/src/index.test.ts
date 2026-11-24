import { strictEqual } from "node:assert/strict";
import { test } from "node:test";
import { greet } from "./index.ts";

test("greets by name", () => {
	strictEqual(greet({ name: "Ada" }), "Hello, Ada");
});
