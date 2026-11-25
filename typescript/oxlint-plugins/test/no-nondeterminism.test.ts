import { describe, expect, it } from "@effect/vitest";
import { Effect } from "effect";
import { findings } from "./oxlint.ts";

const rules = {
  "no-restricted-globals": ["error", "Date", "performance", "crypto"],
  "no-restricted-properties": ["error", { object: "Math", property: "random" }],
} as const;

describe("no-nondeterminism", () => {
  it.effect("reports each nondeterministic global", () =>
    Effect.map(
      findings(
        rules,
        [
          "export const now = (): number => Date.now();",
          "export const today = (): Date => new Date();",
          "export const roll = (): number => Math.random();",
          "export const tick = (): number => performance.now();",
          "export const id = (): string => crypto.randomUUID();",
          "export const fill = (bytes: Uint8Array): Uint8Array => crypto.getRandomValues(bytes);",
          "export const read = (clock: () => number): number => clock();",
          "export const later = (): number => read(Date.now);",
          "export const most = (): number => Math.max(1, 2);",
          "",
        ].join("\n"),
      ),
      (found) => {
        expect(found).toStrictEqual([
          "1 eslint(no-restricted-globals)",
          "2 eslint(no-restricted-globals)",
          "3 eslint(no-restricted-properties)",
          "4 eslint(no-restricted-globals)",
          "5 eslint(no-restricted-globals)",
          "6 eslint(no-restricted-globals)",
          "8 eslint(no-restricted-globals)",
        ]);
      },
    ),
  );

  it.effect("doesn't report a local binding named Date or crypto", () =>
    Effect.map(
      findings(
        rules,
        [
          "const Date = { now: (): number => 0 };",
          "const crypto = { randomUUID: (): string => 'id' };",
          "export const now = (): number => Date.now();",
          "export const id = (): string => crypto.randomUUID();",
          "",
        ].join("\n"),
      ),
      (found) => {
        expect(found).toStrictEqual([]);
      },
    ),
  );
});
