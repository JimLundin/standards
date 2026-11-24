import { describe, expect, it } from "@effect/vitest";
import { Effect } from "effect";
import { findings } from "./test/oxlint.ts";

const rules = { "standards/readonly-types": "error" } as const;

describe("readonly-types", () => {
	it.effect("reports a mutable array, Map or Set in a type position", () =>
		Effect.map(
			findings(
				rules,
				[
					"export type Names = string[];",
					"export type Counts = Array<number>;",
					"export type Index = Map<string, number>;",
					"export type Seen = Set<string>;",
					"export type Grid = readonly number[][];",
					"",
				].join("\n"),
			),
			(found) => {
				expect(found).toStrictEqual([
					"1 standards(readonly-types)",
					"2 standards(readonly-types)",
					"3 standards(readonly-types)",
					"4 standards(readonly-types)",
					"5 standards(readonly-types)",
				]);
			},
		),
	);

	it.effect("doesn't report the readonly forms", () =>
		Effect.map(
			findings(
				rules,
				[
					"export type Names = readonly string[];",
					"export type Counts = ReadonlyArray<number>;",
					"export type Index = ReadonlyMap<string, number>;",
					"export type Seen = ReadonlySet<string>;",
					"export type Grid = readonly (readonly number[])[];",
					"",
				].join("\n"),
			),
			(found) => {
				expect(found).toStrictEqual([]);
			},
		),
	);
});
