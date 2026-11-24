import { describe, expect, it } from "@effect/vitest";
import { Effect } from "effect";
import { findings } from "./oxlint.ts";

const rules = { "standards/no-plain-class": "error" } as const;
const finding = "standards(no-plain-class)";

const plain = `export class Counter {}
export const Anonymous = class {};
class Base {}
export class Derived extends Base {}
`;
const lookalike = `const Schema = { Class: () => () => Object };
const Data = { TaggedError: () => Object };
export class Person extends Schema.Class<Person>("Person")({}) {}
export class Missing extends Data.TaggedError("Missing")<{}> {}
`;
const allowed = `import { Context, Data, Schema } from "effect";

export class Person extends Schema.Class<Person>("Person")({ name: Schema.String }) {}
export class Circle extends Schema.TaggedClass<Circle>()("Circle", { radius: Schema.Number }) {}
export class Invalid extends Schema.TaggedError<Invalid>()("Invalid", { reason: Schema.String }) {}
export class Point extends Data.Class<{ readonly x: number }> {}
export class Square extends Data.TaggedClass("Square")<{ readonly side: number }> {}
export class Missing extends Data.TaggedError("Missing")<{ readonly path: string }> {}
export class Failed extends Data.Error<{ readonly reason: string }> {}
export class Clock extends Context.Service<Clock, { readonly now: number }>()("Clock") {}
`;
const renamed = `import { Data as Values } from "effect";
import * as Schema from "effect/Schema";

export class Person extends Schema.Class<Person>("Person")({}) {}
export class Point extends Values.Class<{ readonly x: number }> {}
`;
const unlisted = `import { Effect, Schema } from "effect";

export class Failed extends Schema.Error<Failed>()({}) {}
export class Logger extends Effect.Service<Logger>()("Logger", {}) {}
`;

describe("no-plain-class", () => {
	it.effect("reports a plain class and a class extending a local class", () =>
		Effect.map(findings(rules, plain), (found) => {
			expect(found).toStrictEqual([
				`1 ${finding}`,
				`2 ${finding}`,
				`3 ${finding}`,
				`4 ${finding}`,
			]);
		}),
	);

	it.effect("reports a class extending a lookalike not imported from effect", () =>
		Effect.map(findings(rules, lookalike), (found) => {
			expect(found).toStrictEqual([`3 ${finding}`, `4 ${finding}`]);
		}),
	);

	it.effect("doesn't report a class extending each allowed Effect base", () =>
		Effect.map(findings(rules, allowed), (found) => {
			expect(found).toStrictEqual([]);
		}),
	);

	it.effect("resolves an aliased or namespace import from effect", () =>
		Effect.map(findings(rules, renamed), (found) => {
			expect(found).toStrictEqual([]);
		}),
	);

	it.effect("reports a class extending an Effect constructor not allowed", () =>
		Effect.map(findings(rules, unlisted), (found) => {
			expect(found).toStrictEqual([`3 ${finding}`, `4 ${finding}`]);
		}),
	);
});
