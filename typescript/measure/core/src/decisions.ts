import type { Binding, Reference } from "./imports.ts";
import type { Kind, Syntax } from "./syntax.ts";
import { bindings, refersTo, resolved } from "./imports.ts";

// A function, or a module's own statements, with the decisions written in it and its closures.
interface Measured {
  readonly name: string;
  readonly line: number;
  readonly decisions: number;
}

interface Tally {
  readonly decisions: number;
  readonly functions: ReadonlyArray<Measured>;
}

const NONE = 0;
const MANY = 2;
const FIRST_LINE = 1;
const MODULE = "(module)";
const ANONYMOUS = "(anonymous)";
const NAMES: Readonly<Partial<Record<Kind, string>>> = {
  constructor: "constructor",
  export: "default",
};
const WRITTEN: ReadonlySet<Kind> = new Set(["conditional", "if", "loop"]);
const LOGICAL: ReadonlySet<Kind> = new Set(["and", "coalesce", "or"]);
// Each combinator that branches, as the export of Effect's barrel that names it; its own module, as `effect/Effect`, exports it too.
const BRANCHING: ReadonlyArray<readonly [string, string]> = [
  ["Effect", "catchTag"],
  ["Effect", "catchTags"],
  ["Effect", "if"],
  ["Effect", "when"],
  ["Match", "tag"],
  ["Match", "when"],
  ["Option", "match"],
  ["Result", "match"],
];
const COMBINATORS: ReadonlyArray<Reference> = BRANCHING.flatMap(([module, name]) => [
  { module: "effect", path: [module, name] },
  { module: `effect/${module}`, path: [name] },
]);
// What a module declares at its top level is measured on its own, as a function is wherever it's declared and a class's member is.
const DECLARED: ReadonlySet<Kind> = new Set(["class", "export", "variable"]);
const MEMBERS: ReadonlySet<Kind> = new Set(["constructor", "member"]);
// Closures and members belong to the function they're written in.
const ENCLOSED: ReadonlySet<Kind> = new Set(["closure", "member"]);

const operator = ({ children: [, token] }: Syntax): Kind => token?.kind ?? "other";

// A run of one logical operator is one decision, counted at its first operator.
const begins = (node: Syntax): boolean => {
  const [left] = node.children;
  return (
    LOGICAL.has(operator(node)) && !(left?.kind === "binary" && operator(left) === operator(node))
  );
};

// Whether a call's callee names a combinator that branches, through the file's imports.
const branches = ({ children: [target] }: Syntax, known: ReadonlyArray<Binding>): boolean => {
  const reference = target === undefined ? undefined : resolved(known, target);
  return (
    reference !== undefined && COMBINATORS.some((combinator) => refersTo(reference, combinator))
  );
};

const cases = (node: Syntax): number =>
  node.children
    .filter((child) => child.kind === "cases")
    .flatMap((block) => block.children)
    .filter((child) => child.kind === "case").length;

const own = (node: Syntax, known: ReadonlyArray<Binding>): boolean =>
  WRITTEN.has(node.kind) ||
  (node.kind === "switch" && cases(node) >= MANY) ||
  (node.kind === "binary" && begins(node)) ||
  (node.kind === "call" && branches(node, known));

const opens = (node: Syntax, parent: Kind, top: boolean): boolean =>
  node.kind === "function" ||
  (parent === "class" && MEMBERS.has(node.kind)) ||
  (top && DECLARED.has(node.kind));

const named = (node: Syntax, decisions: number): Measured => {
  const identifier = node.children.find((child) => child.kind === "identifier");
  return {
    decisions,
    line: identifier?.line ?? node.line,
    name: identifier?.name ?? NAMES[node.kind] ?? ANONYMOUS,
  };
};

const summed = (tallies: ReadonlyArray<Tally>, decisions: number): Tally => ({
  decisions: tallies.reduce((total, tally) => total + tally.decisions, decisions),
  functions: tallies.flatMap((tally) => tally.functions),
});

// The decisions a node leaves to the function it's in, and the functions it opens, outermost first, with the combinators its file imports.
type Visit = (node: Syntax, parent: Kind, top: boolean) => Tally;

const visitor = (known: ReadonlyArray<Binding>): Visit => {
  const visited: Visit = (node, parent, top) => {
    const opened = opens(node, parent, top);
    const inner = summed(
      node.children.map((child) =>
        visited(child, node.kind, top && !opened && !ENCLOSED.has(child.kind)),
      ),
      Number(own(node, known)),
    );
    return opened
      ? { decisions: NONE, functions: [named(node, inner.decisions), ...inner.functions] }
      : inner;
  };
  return visited;
};

// Each function of a source file with its decisions, after its module's own statements if they make any.
const functions = (file: Syntax): ReadonlyArray<Measured> => {
  const { decisions, functions: found } = visitor(bindings(file))(file, "other", true);
  const module: ReadonlyArray<Measured> =
    decisions > NONE ? [{ decisions, line: FIRST_LINE, name: MODULE }] : [];
  return [...module, ...found];
};

export { functions };
export type { Measured };
