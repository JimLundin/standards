// A symbol a type is named by, and the file it's declared in.
interface Origin {
  readonly name: string;
  readonly path: string;
}

// What the checker tells of a type, for the core to judge: data it can't see into, a function with the types of its parameters and returns, a class, or another type with the origins it's named by, its type arguments and the types of its members.
type Shape =
  | { readonly kind: "data" }
  | { readonly kind: "function"; readonly text: string; readonly parts: ReadonlyArray<Shape> }
  | {
      readonly kind: "class";
      readonly bases: ReadonlyArray<Origin>;
      readonly methods: ReadonlyArray<string>;
      readonly members: ReadonlyArray<Shape>;
    }
  | {
      readonly kind: "type";
      readonly origins: ReadonlyArray<Origin>;
      readonly arguments: ReadonlyArray<Shape>;
      readonly members: ReadonlyArray<Shape>;
    };

// An export of a core file, at the line of its export, with the shapes of its value and its type.
interface Export {
  readonly name: string;
  readonly line: number;
  readonly shapes: ReadonlyArray<Shape>;
}

// How much of a type to read: nothing, for one that isn't data whatever its arguments; only its type arguments, for a data type; or all of it.
type Reading = "none" | "arguments" | "all";

const LIB = "lib";
const PACKAGES = "/node_modules/";
const LIBRARY = /^(?:@typescript\/[^/]+|typescript)\/lib\/lib\.[^/]+\.d\.ts$/u;
const SCOPED = /^(@[^/]+\/[^/]+|[^@/][^/]*)\/(?:dist\/)?(.*?)(?:\.d)?\.[cm]?ts$/u;
const NOT_DATA: ReadonlySet<string> = new Set([
  "effect/Context",
  "effect/Effect",
  "effect/Layer",
  "effect/Stream",
]);
const DATA: ReadonlySet<string> = new Set([
  "effect/Data",
  "effect/Option",
  "effect/Result",
  "effect/Schema",
  "effect/http-api/HttpApi",
  "effect/http-api/HttpApiEndpoint",
  "effect/http-api/HttpApiError",
  "effect/http-api/HttpApiGroup",
  "effect/http-api/HttpApiMiddleware",
  "effect/http-api/HttpApiSchema",
  "effect/http-api/HttpApiSecurity",
  "effect/rpc/Rpc",
  "effect/rpc/RpcGroup",
  "effect/rpc/RpcMiddleware",
  "effect/rpc/RpcSchema",
]);
const LIB_DATA: ReadonlySet<string> = new Set(["Array", "ReadonlyArray", "ReadonlyMap", "ReadonlySet"]);
const LIB_NOT_DATA: ReadonlySet<string> = new Set([
  "ArrayIterator",
  "AsyncGenerator",
  "AsyncIterable",
  "AsyncIterableIterator",
  "AsyncIterator",
  "AsyncIteratorObject",
  "Generator",
  "Iterable",
  "IterableIterator",
  "Iterator",
  "IteratorObject",
  "MapIterator",
  "Promise",
  "PromiseLike",
  "SetIterator",
]);
const FIRST = 0;

// The module a file declares into: "lib" for TypeScript's own, a package and its module for a dependency's, as `effect/Schema`, and "" for the project's.
const moduleOf = (path: string): string => {
  const start = path.lastIndexOf(PACKAGES);
  const within = start < FIRST ? "" : path.slice(start + PACKAGES.length);
  const [, name, module] = SCOPED.exec(within) ?? [];
  if (LIBRARY.test(within)) {
    return LIB;
  }
  return name === undefined ? "" : `${name}/${module ?? ""}`;
};

const isData = ({ name, path }: Origin): boolean => {
  const module = moduleOf(path);
  return DATA.has(module) || (module === LIB && LIB_DATA.has(name));
};

// How an origin that isn't data is named in a finding, or "" for one that may be.
const notData = ({ name, path }: Origin): string => {
  const module = moduleOf(path);
  if (NOT_DATA.has(module)) {
    return `\`${module.slice(module.lastIndexOf("/") + 1)}.${name}\``;
  }
  return module === LIB && LIB_NOT_DATA.has(name) ? `\`${name}\`` : "";
};

const found = (origins: ReadonlyArray<Origin>): ReadonlyArray<string> =>
  origins
    .map(notData)
    .filter((named) => named !== "")
    .map((named) => `reaches ${named}`);

const reading = (origins: ReadonlyArray<Origin>): Reading => {
  if (origins.some((origin) => notData(origin) !== "")) {
    return "none";
  }
  return origins.some(isData) ? "arguments" : "all";
};

// What a shape reaches that isn't data; a function at the top of an export is its signature, and only its parts are judged.
const reached = (shape: Shape, top: boolean): ReadonlyArray<string> => {
  switch (shape.kind) {
    case "data":
      return [];
    case "function":
      return top
        ? shape.parts.flatMap((part) => reached(part, false))
        : [`reaches a function type, \`${shape.text}\``];
    case "class":
      return judgedClass(shape);
    case "type":
      return judgedType(shape);
  }
};

const judgedClass = ({
  bases,
  methods,
  members,
}: Extract<Shape, { readonly kind: "class" }>): ReadonlyArray<string> => {
  const read = reading(bases);
  if (read === "none") {
    return found(bases);
  }
  if (read === "arguments") {
    return [];
  }
  return methods.length > FIRST
    ? [`is a class with methods, \`${methods.join("`, `")}\``]
    : members.flatMap((member) => reached(member, false));
};

const judgedType = ({
  origins,
  arguments: parts,
  members,
}: Extract<Shape, { readonly kind: "type" }>): ReadonlyArray<string> => {
  const read = reading(origins);
  if (read === "none") {
    return found(origins);
  }
  const judged = read === "all" ? [...parts, ...members] : parts;
  return judged.flatMap((part) => reached(part, false));
};

// Whether an export whose target is declared at `declared` is judged in `file`: one declared in another of the project's files is judged there. The checker's paths may be lowercased.
const declaredHere = (file: string, declared: string): boolean =>
  declared.toLowerCase() === file.toLowerCase() || declared.includes(PACKAGES);

// Each distinct thing an export reaches that isn't data, as its finding reads: "reaches `Promise`".
const problems = ({ shapes }: Export): ReadonlyArray<string> => [
  ...new Set(shapes.flatMap((shape) => reached(shape, true))),
];

export { declaredHere, problems, reading };
export type { Export, Origin, Reading, Shape };
