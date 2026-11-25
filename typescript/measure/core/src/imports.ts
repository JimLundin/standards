import type { Syntax } from "./syntax.ts";

// A module's export, as the module and the names that reach it from there: `effect` and `["Effect", "if"]`, or `effect/Effect` and `["if"]`.
interface Reference {
  readonly module: string;
  readonly path: ReadonlyArray<string>;
}

// A name an import binds in a file, and the names it stands for in its module: none for the module itself, as a namespace or a default import binds it.
interface Binding {
  readonly local: string;
  readonly module: string;
  readonly names: ReadonlyArray<string>;
}

const NONE = 0;
const FIRST = 0;
const NEXT = 1;
const LAST = -1;

// The names of a specifier's or a namespace import's identifiers, its only children.
const names = (node: Syntax): ReadonlyArray<string> => node.children.map((child) => child.name);

// A specifier binds its last name to its first, as `run` to `runMain` in `runMain as run`.
const specified = (specifier: Syntax, module: string): ReadonlyArray<Binding> => {
  const spelled = names(specifier);
  return spelled.slice(LAST).map((local) => ({ local, module, names: spelled.slice(FIRST, NEXT) }));
};

const bound = (clause: Syntax, module: string): ReadonlyArray<Binding> =>
  clause.children.flatMap((child): ReadonlyArray<Binding> => {
    switch (child.kind) {
      case "identifier": {
        return [{ local: child.name, module, names: [] }];
      }
      case "namespace": {
        return names(child).map((local) => ({ local, module, names: [] }));
      }
      default: {
        return child.children.flatMap((specifier) => specified(specifier, module));
      }
    }
  });

const imported = (declaration: Syntax): ReadonlyArray<Binding> =>
  declaration.children
    .filter((child) => child.kind === "string")
    .flatMap((module) => declaration.children.flatMap((clause) => bound(clause, module.name)));

// The names an expression spells, as `["NodeRuntime", "runMain"]` for `NodeRuntime.runMain`, or none for any other expression.
const spelled = (node: Syntax): ReadonlyArray<string> => {
  if (node.kind === "identifier") {
    return [node.name];
  }
  if (node.kind !== "property") {
    return [];
  }
  const head = node.children.slice(FIRST, NEXT).flatMap((target) => spelled(target));
  return head.length === NONE
    ? []
    : [...head, ...node.children.slice(LAST).map((name) => name.name)];
};

// The names the imports of a file's top level bind.
const bindings = (file: Syntax): ReadonlyArray<Binding> =>
  file.children
    .filter((child) => child.kind === "import")
    .flatMap((declaration) => imported(declaration));

// The export an identifier or a property access names through a file's bindings, called or not, or undefined for any other expression and for a name no import binds.
const resolved = (known: ReadonlyArray<Binding>, node: Syntax): Reference | undefined => {
  const [local, ...rest] = spelled(node);
  const binding = known.find((each) => each.local === local);
  return binding === undefined
    ? undefined
    : { module: binding.module, path: [...binding.names, ...rest] };
};

// Whether a reference names the same export as `module` and `path`.
const refersTo = (reference: Reference, { module, path }: Reference): boolean =>
  reference.module === module && String(reference.path) === String(path);

export { bindings, refersTo, resolved };
export type { Binding, Reference };
