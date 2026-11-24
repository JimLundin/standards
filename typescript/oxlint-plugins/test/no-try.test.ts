import { describe, expect, it } from "@effect/vitest";
import { Effect } from "effect";
import { findings } from "./oxlint.ts";

const rules = { "standards/no-try": "error" } as const;

const tried = `export const guarded = (run: () => number): number => {
	try {
		return run();
	} catch {
		return 0;
	}
};
export const cleaned = (run: () => number, done: () => void): number => {
	try {
		return run();
	} finally {
		done();
	}
};
`;
const lookalikes = `const attempt = { catch: () => "failed", try: () => 1 };
export const tried = (): number => attempt.try();
export const caught = (): string => attempt.catch();
`;

describe("no-try", () => {
  it.effect("reports each try statement, with a catch or a finally", () =>
    Effect.map(findings(rules, tried), (found) => {
      expect(found).toStrictEqual(["2 standards(no-try)", "9 standards(no-try)"]);
    }),
  );

  it.effect("doesn't report a property or method named try or catch", () =>
    Effect.map(findings(rules, lookalikes), (found) => {
      expect(found).toStrictEqual([]);
    }),
  );
});
