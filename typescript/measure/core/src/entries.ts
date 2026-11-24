import type { Syntax } from "./syntax.ts";

type Call = "createRoot" | "runMain";

// A call that starts a runtime: a Node shell's runMain, or a UI's createRoot.
interface Entry {
  readonly call: Call;
  readonly line: number;
}

// Each entry point, as the module that exports it and the names that reach it from that module.
const ENTRIES: ReadonlyArray<readonly [Call, string, ReadonlyArray<string>]> = [
  ["runMain", "@effect/platform-node", ["NodeRuntime", "runMain"]],
  ["runMain", "@effect/platform-node/NodeRuntime", ["runMain"]],
  ["createRoot", "react-dom/client", ["createRoot"]],
];

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

// The names a callee spells, as `["NodeRuntime", "runMain"]` for `NodeRuntime.runMain`, or none for any other expression.
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

const dotted = (path: ReadonlyArray<string>): string => path.join(".");

const resolved = (bindings: ReadonlyArray<Binding>, call: Syntax): ReadonlyArray<Entry> => {
  const [callee] = call.children;
  const [local, ...rest] = callee === undefined ? [] : spelled(callee);
  return bindings
    .filter((binding) => binding.local === local)
    .flatMap((binding) =>
      ENTRIES.flatMap(([name, module, path]) =>
        module === binding.module && dotted(path) === dotted([...binding.names, ...rest])
          ? [{ call: name, line: call.line }]
          : [],
      ),
    );
};

const nodes = (node: Syntax): ReadonlyArray<Syntax> => [node, ...node.children.flatMap(nodes)];

// Each entry point a source file calls, through the imports of its top level, in source order.
const entries = (file: Syntax): ReadonlyArray<Entry> => {
  const bindings = file.children
    .filter((child) => child.kind === "import")
    .flatMap((declaration) => imported(declaration));
  return nodes(file)
    .filter((node) => node.kind === "call")
    .flatMap((call) => resolved(bindings, call));
};

export { entries };
export type { Entry };
