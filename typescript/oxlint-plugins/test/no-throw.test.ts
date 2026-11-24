import { describe, expect, it } from "@effect/vitest";
import { Effect } from "effect";
import { findings } from "./oxlint.ts";

const rules = { "standards/no-throw": "error" } as const;

const thrown = `export const fail = (): never => {
	throw new Error("no");
};
export const rethrow = (reason: unknown): never => {
	throw reason;
};
`;
const lookalikes = `const steps = { throw: "raise" };
export const step = (): string => steps.throw;
export const stop = (iterator: Generator<number>): IteratorResult<number> =>
	iterator.throw(new Error("stop"));
`;

describe("no-throw", () => {
	it.effect("reports each throw statement", () =>
		Effect.map(findings(rules, thrown), (found) => {
			expect(found).toStrictEqual([
				"2 standards(no-throw)",
				"5 standards(no-throw)",
			]);
		}),
	);

	it.effect("doesn't report a property or method named throw", () =>
		Effect.map(findings(rules, lookalikes), (found) => {
			expect(found).toStrictEqual([]);
		}),
	);
});
