import { describe, expect, it } from "@effect/vitest";
import { Effect } from "effect";
import { findings } from "./oxlint.ts";

const rules = { "standards/readonly-members": "error" } as const;

describe("readonly-members", () => {
	it.effect(
		"reports a mutable class property and interface or type-literal member",
		() =>
			Effect.map(
				findings(
					rules,
					[
						"export class Counter {",
						"\tcount = 0;",
						"\t#hidden = 1;",
						"\tread(): number { return this.count + this.#hidden; }",
						"}",
						"export interface Point { x: number }",
						"export type Pair = { left: string };",
						"",
					].join("\n"),
				),
				(found) => {
					expect(found).toStrictEqual([
						"2 standards(readonly-members)",
						"3 standards(readonly-members)",
						"6 standards(readonly-members)",
						"7 standards(readonly-members)",
					]);
				},
			),
	);

	it.effect("doesn't report readonly members", () =>
		Effect.map(
			findings(
				rules,
				[
					"export class Counter {",
					"\treadonly count = 0;",
					"\tstatic readonly start = 0;",
					"\tread(): number { return this.count; }",
					"}",
					"export interface Point { readonly x: number; read(): number }",
					"export type Pair = { readonly left: string };",
					"",
				].join("\n"),
			),
			(found) => {
				expect(found).toStrictEqual([]);
			},
		),
	);
});
