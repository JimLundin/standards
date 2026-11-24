import cloudflare from "@cloudflare/oxlint-config";
import { defineConfig } from "oxlint";

const ambient =
	"ambient input and side effects: pass values in from the boundary";
const boundary = "side effect: keep I/O at the boundary";
const tests = ["**/*.test.ts", "**/test/**"] as const;

export default defineConfig({
	categories: {
		correctness: "error",
		pedantic: "error",
		perf: "error",
		restriction: "error",
		style: "error",
		suspicious: "error",
	},
	extends: [
		{
			...cloudflare,
			// Framework domains stay off, as React and JSX a11y, which cloudflare's base enables.
			plugins: cloudflare.plugins?.filter(
				(plugin) => plugin !== "jsx-a11y" && plugin !== "react",
			),
		},
	],
	options: { typeAware: true },
	overrides: [
		{
			files: [...tests],
			rules: {
				"no-magic-numbers": "off",
			},
		},
		{
			files: ["**/*.config.{ts,mts,js,mjs}"],
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
	plugins: ["typescript", "unicorn", "import", "promise", "oxc", "vitest"],
	rules: {
		// Contradicts import/no-default-export.
		"import/no-named-export": "off",
		// Contradicts import/no-default-export.
		"import/prefer-default-export": "off",
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
		// Contradicts typescript/promise-function-async; typescript/require-await knows a returned promise.
		"require-await": "off",
		// Contradicts typescript/no-non-null-assertion.
		"typescript/non-nullable-type-assertion-style": "off",
		"vitest/consistent-test-it": ["error", { fn: "it", withinDescribe: "it" }],
		// Contradicts vitest/require-hook.
		"vitest/no-hooks": "off",
		// The standard imports it from @effect/vitest, and vitest's globals are off.
		"vitest/no-importing-vitest-globals": "off",
		// Vitest's testTimeout bounds every test; a test sets its own only to need another.
		"vitest/require-test-timeout": "off",
		// Vitest/prefer-describe-function-title names a describe by its function, not a string.
		"vitest/valid-title": ["error", { ignoreTypeOfDescribeName: true }],
	},
});
