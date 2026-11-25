import { describe, expect, it } from "@effect/vitest";
import { Effect } from "effect";
import { findings } from "./oxlint.ts";

const rules = { "standards/no-module-state": "error" } as const;
const finding = "standards(no-module-state)";

const bindings = `let count = 0;
var total = 0;
export const sum = (): number => count + total;
`;
const collections = `const cache = new Map<string, number>();
const seen = new Set<string>();
const names = ["Ada"];
const counts = { ada: 1 };
export const all = (): number => cache.size + seen.size + names.length + counts.ada;
`;
const local = `export const count = (limit: number): number => {
	let total = 0;
	while (total < limit) total += 1;
	return total;
};
`;
const readonly = `const limit = 3;
const names = ["Ada"] as const;
const counts = { ada: 1 } as const satisfies Record<string, number>;
const seen: ReadonlySet<string> = new Set(["Ada"]);
const cache: ReadonlyMap<string, number> = new Map();
const list: readonly string[] = ["Ada"];
export const all = (): number =>
	limit + names.length + counts.ada + seen.size + cache.size + list.length;
`;

describe("no-module-state", () => {
  it.effect("reports a module-level let and var", () =>
    Effect.map(findings(rules, bindings), (found) => {
      expect(found).toStrictEqual([`1 ${finding}`, `2 ${finding}`]);
    }),
  );

  it.effect("reports a module-level mutable collection", () =>
    Effect.map(findings(rules, collections), (found) => {
      expect(found).toStrictEqual([`1 ${finding}`, `2 ${finding}`, `3 ${finding}`, `4 ${finding}`]);
    }),
  );

  it.effect("doesn't report a let inside a function", () =>
    Effect.map(findings(rules, local), (found) => {
      expect(found).toStrictEqual([]);
    }),
  );

  it.effect("doesn't report a module-level const of a readonly value", () =>
    Effect.map(findings(rules, readonly), (found) => {
      expect(found).toStrictEqual([]);
    }),
  );
});
