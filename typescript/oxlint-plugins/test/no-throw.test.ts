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

describe("no-throw", () => {
  it.effect("reports each throw statement", () =>
    Effect.map(findings(rules, thrown), (found) => {
      expect(found).toStrictEqual(["2 standards(no-throw)", "5 standards(no-throw)"]);
    }),
  );
});
