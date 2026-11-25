import type { BadArgument, PlatformError } from "effect/PlatformError";
import { ChildProcess, ChildProcessSpawner } from "effect/process";
import { Effect, FileSystem, Path, Schema } from "effect";
import { NodeServices } from "@effect/platform-node";
import type { Scope } from "effect";

const Label = Schema.Struct({ span: Schema.Struct({ line: Schema.Number }) });
const Diagnostic = Schema.Struct({
  code: Schema.String,
  labels: Schema.Array(Label),
});
const Report = Schema.fromJsonString(Schema.Struct({ diagnostics: Schema.Array(Diagnostic) }));

const plugin = new URL("../index.ts", import.meta.url);
const oxlint = new URL("../node_modules/oxlint/bin/oxlint", import.meta.url);

type Rules = Readonly<Record<string, string | ReadonlyArray<unknown>>>;

const written = (
  rules: Rules,
  source: string,
): Effect.Effect<
  readonly [string, string],
  PlatformError,
  FileSystem.FileSystem | Path.Path | Scope.Scope
> =>
  Effect.gen(function* write() {
    const files = yield* FileSystem.FileSystem;
    const path = yield* Path.Path;
    const folder = yield* files.makeTempDirectoryScoped();
    const config = path.join(folder, "oxlintrc.json");
    const example = path.join(folder, "example.ts");
    const settings = {
      categories: { correctness: "off" },
      jsPlugins: [plugin.href],
      plugins: [],
      rules,
    };
    yield* files.writeFileString(config, JSON.stringify(settings));
    yield* files.writeFileString(example, source);
    return [config, example] as const;
  });

export const findings = (
  rules: Rules,
  source: string,
): Effect.Effect<ReadonlyArray<string>, BadArgument | PlatformError | Schema.SchemaError> =>
  Effect.gen(function* lint() {
    const [config, example] = yield* written(rules, source);
    const path = yield* Path.Path;
    const binary = yield* path.fromFileUrl(oxlint);
    const spawner = yield* ChildProcessSpawner.ChildProcessSpawner;
    const flags = [binary, "--config", config, "--format", "json", example];
    const output = yield* spawner.string(ChildProcess.make("node", flags));
    const { diagnostics } = yield* Schema.decodeUnknownEffect(Report)(output);
    return diagnostics
      .flatMap(({ code, labels }) => labels.map(({ span }) => [span.line, code] as const))
      .toSorted(([left], [right]) => left - right)
      .map(([line, code]) => `${line} ${code}`);
  }).pipe(Effect.scoped, Effect.provide(NodeServices.layer));
