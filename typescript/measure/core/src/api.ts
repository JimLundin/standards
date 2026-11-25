// A symbol a type is named by, and the file it's declared in.
interface Origin {
  readonly name: string;
  readonly path: string;
}

// What the checker tells of a type, for the core to judge: data it can't see into, a function with the types of its signatures' parameters and returns, a class, or another type with the origins it's named by, its type arguments and the types of its members.
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

// What the shell first reads of a type, to plan how much more of it to read: its checker id and flags, the flags of its symbol, its origins and its signatures.
interface Look {
  readonly id: number;
  readonly flags: number;
  readonly symbolFlags: number;
  readonly origins: ReadonlyArray<Origin>;
  readonly calls: number;
  readonly constructs: number;
  readonly tuple: boolean;
}

// How much of a type to read: nothing, for one that isn't data whatever its arguments; only its type arguments, for a data type; or all of it.
type Reading = "none" | "arguments" | "all";

// What the shell reads of a type next: nothing more, for data or a type that isn't data; its type arguments; a function's text, with its signatures' parameters and returns at the top of an export; a class's instances; or all of its members.
type Plan = "data" | "named" | "arguments" | "function" | "signatures" | "class" | "members";

// What the shell reads of an exported symbol: the class it declares, or its value's type and its declared type.
type Part = "class" | "value" | "type";

// The flags of TypeScript 7's TypeFlags and SymbolFlags that the plans read.
const OBJECT = 1_048_576;
const UNION = 134_217_728;
const INTERSECTION = 268_435_456;
const CLASS = 32;
const INTERFACE = 64;
const TYPE_ALIAS = 524_288;
const VALUE = 111_551;
const METHOD = 8192;
const ALIAS = 2_097_152;
const STRUCTURED: ReadonlyArray<number> = [OBJECT, UNION, INTERSECTION];
const FLAGS = 32;
const BINARY = 2;
const BITS: ReadonlyArray<number> = Array.from(
  { length: FLAGS },
  (_unused, index) => BINARY ** index,
);
const NONE = 0;
const NEXT = 1;

const LIB = "lib";
const PACKAGES = "/node_modules/";
const LIBRARY = /^(?:@typescript\/[^/]+|typescript)\/lib\/lib\.[^/]+\.d\.ts$/u;
const MODULE = /^(?<name>@[^/]+\/[^/]+|[^@/][^/]*)\/(?:dist\/)?(?<module>.*?)(?:\.d)?\.[cm]?ts$/u;
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
const LIB_DATA: ReadonlySet<string> = new Set([
  "Array",
  "Readonly",
  "ReadonlyArray",
  "ReadonlyMap",
  "ReadonlySet",
]);
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

const isSet = (flags: number, bit: number): boolean => Math.floor(flags / bit) % BINARY === NEXT;

// Whether `flags` has any of the flags of `masks`, without bitwise operators.
const flagged = (flags: number, masks: ReadonlyArray<number>): boolean =>
  masks.some((mask) => BITS.some((bit) => isSet(mask, bit) && isSet(flags, bit)));

// The module a file declares into: "lib" for TypeScript's own, a package and its module for a dependency's, as `effect/Schema`, and "" for the project's.
const moduleOf = (path: string): string => {
  const start = path.lastIndexOf(PACKAGES);
  const within = start < NONE ? "" : path.slice(start + PACKAGES.length);
  const groups = MODULE.exec(within)?.groups;
  if (LIBRARY.test(within)) {
    return LIB;
  }
  return groups?.["name"] === undefined ? "" : `${groups["name"]}/${groups["module"] ?? ""}`;
};

const isData = ({ name, path }: Origin): boolean => {
  const module = moduleOf(path);
  return DATA.has(module) || (module === LIB && LIB_DATA.has(name));
};

// How an origin that isn't data is named in a finding, or "" for one that may be.
const notData = ({ name, path }: Origin): string => {
  const module = moduleOf(path);
  if (NOT_DATA.has(module)) {
    return `\`${module.slice(module.lastIndexOf("/") + NEXT)}.${name}\``;
  }
  return module === LIB && LIB_NOT_DATA.has(name) ? `\`${name}\`` : "";
};

const reading = (origins: ReadonlyArray<Origin>): Reading => {
  if (origins.some((origin) => notData(origin) !== "")) {
    return "none";
  }
  return origins.some((origin) => isData(origin)) ? "arguments" : "all";
};

const READS: Readonly<Record<Reading, Plan>> = {
  all: "members",
  arguments: "arguments",
  none: "named",
};

const isInstance = ({ symbolFlags, constructs }: Look): boolean =>
  flagged(symbolFlags, [CLASS]) && constructs === NONE;

// What to read next of a type looked at inside the types of `inside`, at the top of an export or not.
const plan = (look: Look, inside: ReadonlyArray<number>, top: boolean): Plan => {
  if (!flagged(look.flags, STRUCTURED) || inside.includes(look.id)) {
    return "data";
  }
  if (isInstance(look)) {
    return "class";
  }
  const read = READS[reading(look.origins)];
  if (read !== "members" || look.tuple) {
    return read === "members" ? "arguments" : read;
  }
  if (look.calls + look.constructs === NONE) {
    return read;
  }
  return top ? "signatures" : "function";
};

// What to read of an exported symbol, by its flags.
const partsOf = (flags: number): ReadonlyArray<Part> => {
  if (flagged(flags, [CLASS])) {
    return ["class"];
  }
  const value: ReadonlyArray<Part> = flagged(flags, [VALUE]) ? ["value"] : [];
  const type: ReadonlyArray<Part> = flagged(flags, [INTERFACE, TYPE_ALIAS]) ? ["type"] : [];
  return [...value, ...type];
};

const isAlias = (flags: number): boolean => flagged(flags, [ALIAS]);

const isMethod = (flags: number): boolean => flagged(flags, [METHOD]);

// Whether a class's members are read, by the origins of the class it extends.
const readsMembers = (bases: ReadonlyArray<Origin>): boolean => reading(bases) === "all";

// Whether an export whose target is declared at `declared` is judged in `file`: one declared in another of the project's files is judged there. The checker's paths may be lowercased.
const declaredHere = (file: string, declared: string): boolean =>
  declared.toLowerCase() === file.toLowerCase() || declared.includes(PACKAGES);

const found = (origins: ReadonlyArray<Origin>): ReadonlyArray<string> =>
  origins.flatMap((origin) => {
    const named = notData(origin);
    return named === "" ? [] : [`reaches ${named}`];
  });

type Judge = (shape: Shape) => ReadonlyArray<string>;

const classReached = (
  { bases, methods, members }: Extract<Shape, { readonly kind: "class" }>,
  top: boolean,
  inner: Judge,
): ReadonlyArray<string> => {
  if (!readsMembers(bases)) {
    return found(bases);
  }
  return methods.length > NONE
    ? [`${top ? "is" : "reaches"} a class with methods, \`${methods.join("`, `")}\``]
    : members.flatMap((member) => inner(member));
};

const typeReached = (
  { origins, arguments: parts, members }: Extract<Shape, { readonly kind: "type" }>,
  inner: Judge,
): ReadonlyArray<string> => {
  const read = reading(origins);
  if (read === "none") {
    return found(origins);
  }
  return [...parts, ...(read === "all" ? members : [])].flatMap((part) => inner(part));
};

// What a shape reaches that isn't data, as its finding reads: "reaches `Promise`". A function at the top of an export is its signature, of which only the parts are judged, and a class there is the export.
const reached = (shape: Shape, top: boolean): ReadonlyArray<string> => {
  const inner = (part: Shape): ReadonlyArray<string> => reached(part, false);
  switch (shape.kind) {
    case "function": {
      return top
        ? shape.parts.flatMap((part) => inner(part))
        : [`reaches a function type, \`${shape.text}\``];
    }
    case "class": {
      return classReached(shape, top, inner);
    }
    case "type": {
      return typeReached(shape, inner);
    }
    default: {
      return [];
    }
  }
};

// Each distinct thing an export reaches that isn't data.
const problems = ({ shapes }: Export): ReadonlyArray<string> => [
  ...new Set(shapes.flatMap((shape) => reached(shape, true))),
];

export { declaredHere, isAlias, isMethod, partsOf, plan, problems, readsMembers };
export type { Export, Look, Origin, Part, Plan, Shape };
