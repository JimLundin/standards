import cloudflare from "@cloudflare/oxlint-config";
import { defineConfig } from "oxlint";
import standards from "./oxlint-plugins/index.ts";

const ambient = "ambient input and side effects: pass values in from the boundary";
const boundary = "side effect: keep I/O at the boundary";
const nondeterministic = "nondeterministic: pass the value in from the boundary";
const tests = ["**/*.test.{ts,tsx}", "**/test/**"] as const;
const olderEngines = "It forbids syntax for older engines than the standard's target, esnext.";

const strictMatchers =
  "Strict boolean matchers retain the distinction between false and any falsy value.";

const off = {
  "import/no-default-export": "A tool reads its config file's default export.",
  "import/no-named-export": "Contradicts import/no-default-export.",
  "import/prefer-default-export": "Contradicts import/no-default-export.",
  "no-magic-numbers": "A test states the values it expects as literals.",
  "no-ternary": "Contradicts unicorn/prefer-ternary.",
  "no-undefined":
    "With unicorn/no-typeof-undefined and eqeqeq, it leaves no way to test for undefined.",
  "oxc/no-async-await": olderEngines,
  "oxc/no-optional-chaining": olderEngines,
  "oxc/no-rest-spread-properties": olderEngines,
  "react/react-in-jsx-scope":
    "The automatic JSX runtime imports what JSX compiles to, so React needn't be in scope.",
  "require-await":
    "Typescript/require-await, which knows a returned promise, checks async functions in its place.",
  "typescript/non-nullable-type-assertion-style": "Contradicts typescript/no-non-null-assertion.",
  "typescript/promise-function-async":
    "Promise-library adapters, including Effect.tryPromise callbacks, can return a Promise directly.",
  "unicorn/no-array-method-this-argument":
    "Effect's data-first combinators, such as Effect.map(self, f), look to it like a callback with a thisArg.",
  "vitest/no-hooks": "Contradicts vitest/require-hook.",
  "vitest/no-importing-vitest-globals":
    "The standard imports it from @effect/vitest, and vitest's globals are off.",
  "vitest/prefer-to-be-falsy": strictMatchers,
  "vitest/prefer-to-be-truthy": strictMatchers,
  "vitest/require-hook":
    "Outside test files a top-level call is an entry point, such as NodeRuntime.runMain; test files turn it on.",
  "vitest/require-test-timeout":
    "Vitest's testTimeout bounds every test; a test sets its own only to need another.",
  "vitest/require-top-level-describe":
    "A setup file's hooks run around every test file, outside any describe.",
} as const satisfies Record<string, string>;

type Off = keyof typeof off;

const scoped = [
  { files: tests, off: ["no-magic-numbers"], on: ["vitest/require-hook"] },
  { files: ["**/*.config.{ts,tsx,mts,js,mjs}"], off: ["import/no-default-export"], on: [] },
  { files: ["**/vitest.setup.ts"], off: ["vitest/require-top-level-describe"], on: [] },
] as const satisfies ReadonlyArray<{
  readonly files: ReadonlyArray<string>;
  readonly off: ReadonlyArray<Off>;
  readonly on: ReadonlyArray<Off>;
}>;

const isScoped = (rule: string): boolean =>
  scoped.some((scope) => scope.off.some((scopedRule) => scopedRule === rule));

const tuned = {
  "new-cap": {
    options: { capIsNewExceptionPattern: String.raw`^[A-Z]\w*\.[A-Z]` },
    reason:
      "Effect's constructors are capitalised members of a capitalised module, such as Schema.Struct and Config.String.",
  },
  "no-duplicate-imports": {
    options: { allowSeparateTypeImports: true },
    reason:
      "Cloudflare's import/consistent-type-specifier-style puts type imports in their own declaration.",
  },
  "no-underscore-dangle": {
    options: { allow: ["_tag"] },
    reason: "Effect's tagged data uses this discriminator as part of its contract.",
  },
  "one-var": {
    options: "never",
    reason:
      'Its default, "always", merges every declaration of a scope into one; each stands alone.',
  },
  "react/function-component-definition": {
    options: { namedComponents: "arrow-function", unnamedComponents: "arrow-function" },
    reason: "Its default, a function declaration, contradicts func-style.",
  },
  "react/jsx-filename-extension": {
    options: { extensions: [".tsx"] },
    reason: "Its default allows JSX only in .jsx files; the standard's JSX is in .tsx files.",
  },
  "vitest/no-standalone-expect": {
    options: { additionalTestBlockFunctions: ["it.effect", "it.prop"] },
    reason: "@effect/vitest's it.effect and it.prop run a test, as it does.",
  },
  "vitest/valid-title": {
    options: { ignoreTypeOfDescribeName: true },
    reason: "Vitest/prefer-describe-function-title names a describe by its function, not a string.",
  },
} as const satisfies Record<string, { readonly options: unknown; readonly reason: string }>;

export default defineConfig({
  categories: {
    correctness: "error",
    pedantic: "error",
    perf: "error",
    restriction: "error",
    style: "error",
    suspicious: "error",
  },
  extends: [cloudflare],
  jsPlugins: [
    {
      name: "standards",
      specifier: import.meta.resolve("./oxlint-plugins/index.ts"),
    },
  ],
  options: { respectEslintDisableDirectives: false, typeAware: true },
  overrides: scoped.map(({ files, off: scopedOff, on }) => ({
    files: [...files],
    rules: {
      ...Object.fromEntries(scopedOff.map((rule) => [rule, "off" as const])),
      ...Object.fromEntries(on.map((rule) => [rule, "error" as const])),
    },
  })),
  plugins: [
    "typescript",
    "unicorn",
    "import",
    "promise",
    "oxc",
    "vitest",
    "react",
    "react-perf",
    "jsx-a11y",
  ],
  rules: {
    ...Object.fromEntries(
      Object.keys(standards.rules).map((rule) => [`standards/${rule}`, "error" as const]),
    ),
    ...Object.fromEntries(
      Object.keys(off)
        .filter((rule) => !isScoped(rule))
        .map((rule) => [rule, "off" as const]),
    ),
    ...Object.fromEntries(
      Object.entries(tuned).map(([rule, { options }]) => [rule, ["error", options] as const]),
    ),
    "no-restricted-globals": [
      "error",
      { message: ambient, name: "process" },
      { message: boundary, name: "fetch" },
      { message: boundary, name: "setTimeout" },
      { message: boundary, name: "setInterval" },
      { message: boundary, name: "setImmediate" },
      { message: boundary, name: "queueMicrotask" },
      { message: nondeterministic, name: "Date" },
      { message: nondeterministic, name: "performance" },
      { message: nondeterministic, name: "crypto" },
    ],
    "no-restricted-properties": [
      "error",
      { message: nondeterministic, object: "Math", property: "random" },
    ],
    "vitest/consistent-test-it": ["error", { fn: "it", withinDescribe: "it" }],
  },
});
