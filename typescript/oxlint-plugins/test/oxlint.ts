import { NodeServices } from "@effect/platform-node";
import { Effect, FileSystem, Path, Schema } from "effect";
import type { PlatformError } from "effect/PlatformError";
import { ChildProcess, ChildProcessSpawner } from "effect/process";

const Report = Schema.fromJsonString(
	Schema.Struct({
		diagnostics: Schema.Array(
			Schema.Struct({
				code: Schema.String,
				labels: Schema.Array(Schema.Struct({ span: Schema.Struct({ line: Schema.Number }) })),
			}),
		),
	}),
);

const plugin = new URL("../index.ts", import.meta.url);
const oxlint = new URL("../node_modules/oxlint/bin/oxlint", import.meta.url);

// The pinned Oxlint, with the standards plugin and only the given rules on,
// over one example file: each finding as its line and rule, by line.
export const findings = (
	rules: Readonly<Record<string, string | readonly unknown[]>>,
	source: string,
): Effect.Effect<readonly string[], PlatformError | Schema.SchemaError> =>
	Effect.gen(function* () {
		const files = yield* FileSystem.FileSystem;
		const path = yield* Path.Path;
		const spawner = yield* ChildProcessSpawner.ChildProcessSpawner;
		const folder = yield* files.makeTempDirectoryScoped();
		const config = path.join(folder, "oxlintrc.json");
		const example = path.join(folder, "example.ts");
		yield* files.writeFileString(
			config,
			JSON.stringify({
				categories: { correctness: "off" },
				jsPlugins: [plugin.href],
				plugins: [],
				rules,
			}),
		);
		yield* files.writeFileString(example, source);
		const output = yield* spawner.string(
			ChildProcess.make("node", [
				yield* path.fromFileUrl(oxlint),
				"--config",
				config,
				"--format",
				"json",
				example,
			]),
		);
		const report = yield* Schema.decodeUnknownEffect(Report)(output);
		return report.diagnostics
			.flatMap(({ code, labels }) => labels.map(({ span }) => ({ code, line: span.line })))
			.toSorted((left, right) => left.line - right.line)
			.map(({ code, line }) => `${line} ${code}`);
	}).pipe(Effect.scoped, Effect.provide(NodeServices.layer));
