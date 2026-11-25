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

const names = (node: Syntax): ReadonlyArray<string> =>
  node.children.filter((child) => child.kind === "identifier").map((child) => child.name);

const specified = (specifier: Syntax, module: string): ReadonlyArray<Binding> => {
  const [imported, local = imported] = names(specifier);
  return imported === undefined || local === undefined
    ? []
    : [{ local, module, names: [imported] }];
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
        return child.children
          .filter((specifier) => specifier.kind === "specifier")
          .flatMap((specifier) => specified(specifier, module));
      }
    }
  });

const imported = (declaration: Syntax): ReadonlyArray<Binding> => {
  const module = declaration.children.find((child) => child.kind === "string")?.name ?? "";
  return declaration.children
    .filter((child) => child.kind === "clause")
    .flatMap((clause) => bound(clause, module));
};

// The names an expression spells, as `["NodeRuntime", "runMain"]` for `NodeRuntime.runMain`, or none for any other expression.
const spelled = (node: Syntax): ReadonlyArray<string> => {
  if (node.kind === "identifier") {
    return [node.name];
  }
  const [target, ...rest] = node.children;
  const name = rest.findLast((child) => child.kind === "identifier");
  const head = node.kind === "property" && target !== undefined ? spelled(target) : [];
  const [first] = head;
  return first !== undefined && name !== undefined ? [...head, name.name] : [];
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

const dotted = (path: ReadonlyArray<string>): string => path.join(".");

// Whether a reference names the same export as `module` and `path`.
const refersTo = (reference: Reference, { module, path }: Reference): boolean =>
  reference.module === module && dotted(reference.path) === dotted(path);

export { bindings, refersTo, resolved };
export type { Binding, Reference };
