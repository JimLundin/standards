import cloudflare from "@cloudflare/oxlint-config";
import { defineConfig } from "oxlint";
import standards from "./oxlint-plugins/index.ts";

const ambient =
	"ambient input and side effects: pass values in from the boundary";
const boundary = "side effect: keep I/O at the boundary";
const nondeterministic =
	"nondeterministic: pass the value in from the boundary";
const tests = ["**/*.test.{ts,tsx}", "**/test/**"] as const;

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
	// The standards plugin sits beside this file, wherever a run copies it.
	// Named, it resolves under its name, which drift compares.
	jsPlugins: [
		{
			name: "standards",
			specifier: import.meta.resolve("./oxlint-plugins/index.ts"),
		},
	],
	// A rule is turned off in exceptions.toml, never by a comment.
	options: { respectEslintDisableDirectives: false, typeAware: true },
	overrides: [
		{
			files: [...tests],
			rules: {
				"no-magic-numbers": "off",
				// A test file's top-level setup belongs in a hook; see require-hook off below.
				"vitest/require-hook": "error",
			},
		},
		{
			files: ["**/*.config.{ts,tsx,mts,js,mjs}"],
			rules: {
				// A tool reads its config file's default export.
				"import/no-default-export": "off",
			},
		},
		{
			files: ["**/vitest.setup.ts"],
			rules: {
				// A setup file's hooks run around every test file, outside any describe.
				"vitest/require-top-level-describe": "off",
			},
		},
	],
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
			Object.keys(standards.rules).map((rule) => [
				`standards/${rule}`,
				"error" as const,
			]),
		),
		// Contradicts import/no-default-export.
		"import/no-named-export": "off",
		// Contradicts import/no-default-export.
		"import/prefer-default-export": "off",
		// Effect's constructors are capitalised members of a capitalised module, such as Schema.Struct and Config.String.
		"new-cap": [
			"error",
			{ capIsNewExceptionPattern: String.raw`^[A-Z]\w*\.[A-Z]` },
		],
		// Cloudflare's import/consistent-type-specifier-style puts type imports in their own declaration.
		"no-duplicate-imports": ["error", { allowSeparateTypeImports: true }],
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
		// Contradicts unicorn/prefer-ternary.
		"no-ternary": "off",
		// With unicorn/no-typeof-undefined and eqeqeq, it leaves no way to test for undefined.
		"no-undefined": "off",
		// Its default, "always", merges every declaration of a scope into one; each stands alone.
		"one-var": ["error", "never"],
		// These forbid syntax for older engines than the standard's target, esnext.
		"oxc/no-async-await": "off",
		"oxc/no-optional-chaining": "off",
		"oxc/no-rest-spread-properties": "off",
		// Its default, a function declaration, contradicts func-style.
		"react/function-component-definition": [
			"error",
			{
				namedComponents: "arrow-function",
				unnamedComponents: "arrow-function",
			},
		],
		// Its default allows JSX only in .jsx files; the standard's JSX is in .tsx files.
		"react/jsx-filename-extension": ["error", { extensions: [".tsx"] }],
		// The automatic JSX runtime imports what JSX compiles to, so React needn't be in scope.
		"react/react-in-jsx-scope": "off",
		// Contradicts typescript/promise-function-async; typescript/require-await knows a returned promise.
		"require-await": "off",
		// Contradicts typescript/no-non-null-assertion.
		"typescript/non-nullable-type-assertion-style": "off",
		// A callback's parameter takes its type from the API it's passed to, such as an Effect service, which carries mutable markers.
		"typescript/prefer-readonly-parameter-types": [
			"error",
			{ ignoreInferredTypes: true },
		],
		// Effect's data-first combinators, such as Effect.map(self, f), look to it like a callback with a thisArg.
		"unicorn/no-array-method-this-argument": "off",
		"vitest/consistent-test-it": ["error", { fn: "it", withinDescribe: "it" }],
		// Contradicts vitest/require-hook.
		"vitest/no-hooks": "off",
		// The standard imports it from @effect/vitest, and vitest's globals are off.
		"vitest/no-importing-vitest-globals": "off",
		// @effect/vitest's it.effect and it.prop run a test, as it does.
		"vitest/no-standalone-expect": [
			"error",
			{ additionalTestBlockFunctions: ["it.effect", "it.prop"] },
		],
		// Contradicts vitest/prefer-strict-boolean-matchers, which asks for toBe(true).
		"vitest/prefer-to-be-truthy": "off",
		// Outside test files a top-level call is an entry point, such as NodeRuntime.runMain; test files turn it on.
		"vitest/require-hook": "off",
		// Vitest's testTimeout bounds every test; a test sets its own only to need another.
		"vitest/require-test-timeout": "off",
		// Vitest/prefer-describe-function-title names a describe by its function, not a string.
		"vitest/valid-title": ["error", { ignoreTypeOfDescribeName: true }],
	},
});
