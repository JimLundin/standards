import type { API as Compiler, Snapshot } from "typescript/unstable/sync";
import { Data, Effect, FileSystem, Path, Schema } from "effect";
import { LayerMap, failure, fields, functions, record } from "@standards/measure-core";
import { API } from "typescript/unstable/sync";
import type { Placement } from "@standards/measure-core";
import type { PlatformError } from "effect/PlatformError";
import type { Scope } from "effect";
import { api } from "./api.ts";
import { syntaxOf } from "./syntax.ts";

const ABSENT = "not in the project";

class CompilerError extends Data.TaggedError("CompilerError")<{ readonly cause: unknown }> {}

const compiled = <Value>(run: () => Value): Effect.Effect<Value, CompilerError> =>
  Effect.try({ catch: (cause) => new CompilerError({ cause }), try: run });

// The TypeScript 7 API's snapshot of a project with `files` open, closed with the scope.
const opened = (
  project: string,
  files: ReadonlyArray<string>,
): Effect.Effect<Snapshot, CompilerError, Scope.Scope> =>
  Effect.acquireRelease(
    compiled(() => new API({ cwd: project })),
    (compiler: Compiler) =>
      Effect.sync(() => {
        compiler.close();
      }),
  ).pipe(
    Effect.flatMap((compiler) =>
      compiled(() => compiler.updateSnapshot({ openFiles: [...files] })),
    ),
  );

const measured = (
  snapshot: Snapshot,
  file: string,
  placement: Placement,
): ReadonlyArray<string> => {
  const project = snapshot.getDefaultProjectForFile(file);
  const source = project?.program.getSourceFile(file);
  return project === undefined || source === undefined
    ? [failure(placement, ABSENT)]
    : [
        ...functions(syntaxOf(source)).map((found) => record(placement, found)),
        ...api(project, source, placement),
      ];
};

// The record lines of each file of the layer map at `layers`, whose paths are relative to `project`.
const measure = (
  project: string,
  layers: string,
): Effect.Effect<
  ReadonlyArray<string>,
  CompilerError | PlatformError | Schema.SchemaError,
  FileSystem.FileSystem | Path.Path
> =>
  Effect.gen(function* measureProject() {
    const fileSystem = yield* FileSystem.FileSystem;
    const path = yield* Path.Path;
    const text = yield* fileSystem.readFileString(layers);
    const placements = yield* Schema.decodeUnknownEffect(LayerMap)(fields(text));
    const targets = placements.map((placement) => ({
      file: path.resolve(project, placement.path),
      placement,
    }));
    const snapshot = yield* opened(
      project,
      targets.map(({ file }) => file),
    );
    return targets.flatMap(({ file, placement }) => measured(snapshot, file, placement));
  }).pipe(Effect.scoped);

export { measure };
