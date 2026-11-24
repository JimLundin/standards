import { describe, expect, it } from "@effect/vitest";
import { Effect } from "effect";
import { findings } from "./test/oxlint.ts";

const rules = { "standards/no-module-state": "error" } as const;

describe("no-module-state", () => {
	it.effect("reports a module-level let and var", () =>
		Effect.map(
			findings(rules, "let count = 0;\nvar total = 0;\nexport const sum = (): number => count + total;\n"),
			(found) => {
				expect(found).toStrictEqual(["1 standards(no-module-state)", "2 standards(no-module-state)"]);
			},
		),
	);

	it.effect("reports a module-level mutable collection", () =>
		Effect.map(
			findings(
				rules,
				[
					"const cache = new Map<string, number>();",
					"const seen = new Set<string>();",
					"const names = ['Ada'];",
					"const counts = { ada: 1 };",
					"export const all = (): number => cache.size + seen.size + names.length + counts.ada;",
					"",
				].join("\n"),
			),
			(found) => {
				expect(found).toStrictEqual([
					"1 standards(no-module-state)",
					"2 standards(no-module-state)",
					"3 standards(no-module-state)",
					"4 standards(no-module-state)",
				]);
			},
		),
	);

	it.effect("doesn't report a let inside a function", () =>
		Effect.map(
			findings(
				rules,
				"export const count = (limit: number): number => {\n\tlet total = 0;\n\twhile (total < limit) total += 1;\n\treturn total;\n};\n",
			),
			(found) => {
				expect(found).toStrictEqual([]);
			},
		),
	);

	it.effect("doesn't report a module-level const of a readonly value", () =>
		Effect.map(
			findings(
				rules,
				[
					"const limit = 3;",
					"const names = ['Ada'] as const;",
					"const counts = { ada: 1 } as const satisfies Record<string, number>;",
					"const seen: ReadonlySet<string> = new Set(['Ada']);",
					"const cache: ReadonlyMap<string, number> = new Map();",
					"const list: readonly string[] = ['Ada'];",
					"export const all = (): number => limit + names.length + counts.ada + seen.size + cache.size + list.length;",
					"",
				].join("\n"),
			),
			(found) => {
				expect(found).toStrictEqual([]);
			},
		),
	);
});
