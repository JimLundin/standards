import { bindings, refersTo, resolved } from "./imports.ts";
import type { Reference } from "./imports.ts";
import type { Syntax } from "./syntax.ts";

type Call = "createRoot" | "runMain";

// A use of a function that starts a runtime, called or passed as a value: a Node shell's runMain, or a UI's createRoot.
interface Entry {
  readonly call: Call;
  readonly line: number;
}

// Each entry point, as the export that names it.
const ENTRIES: ReadonlyArray<readonly [Call, Reference]> = [
  ["runMain", { module: "@effect/platform-node", path: ["NodeRuntime", "runMain"] }],
  ["runMain", { module: "@effect/platform-node/NodeRuntime", path: ["runMain"] }],
  ["createRoot", { module: "react-dom/client", path: ["createRoot"] }],
];

// The expressions that may name an export, outermost first: an identifier, or a property access and then its target, but never the name after its dot, nor an import's own names.
const expressions = (node: Syntax): ReadonlyArray<Syntax> => {
  switch (node.kind) {
    case "import": {
      return [];
    }
    case "identifier": {
      return [node];
    }
    case "property": {
      const [target] = node.children;
      return [node, ...(target === undefined ? [] : expressions(target))];
    }
    default: {
      return node.children.flatMap(expressions);
    }
  }
};

// Each use of an entry point in a source file, through the imports of its top level, in source order.
const entries = (file: Syntax): ReadonlyArray<Entry> => {
  const known = bindings(file);
  return expressions(file).flatMap((node) => {
    const reference = resolved(known, node);
    return reference === undefined
      ? []
      : ENTRIES.flatMap(([call, entry]) =>
          refersTo(reference, entry) ? [{ call, line: node.line }] : [],
        );
  });
};

export { entries };
export type { Entry };
