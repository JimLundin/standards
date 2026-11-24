import type { Context, ESTree, Rule, Scope, Variable } from "@oxlint/plugins";

// Each Effect module's constructors that a class may extend.
const bases: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ["Context", new Set(["Service"])],
  ["Data", new Set(["Class", "Error", "TaggedClass", "TaggedError"])],
  ["Schema", new Set(["Class", "TaggedClass", "TaggedError"])],
]);

const lookup = (scope: Scope | null, name: string): Variable | undefined =>
  scope === null ? undefined : (scope.set.get(name) ?? lookup(scope.upper, name));

const named = (name: ESTree.IdentifierName | ESTree.StringLiteral): string =>
  name.type === "Identifier" ? name.name : name.value;

// The Effect module a binding imports: `{ Schema } from "effect"` or `* as Schema from "effect/Schema"`.
const effectModule = (variable: Variable | undefined): string | undefined => {
  const [definition] = variable?.defs ?? [];
  if (definition?.type !== "ImportBinding" || definition.parent?.type !== "ImportDeclaration") {
    return undefined;
  }
  const source = definition.parent.source.value;
  const { node } = definition;
  if (node.type === "ImportSpecifier" && source === "effect") {
    return named(node.imported);
  }
  if (node.type === "ImportNamespaceSpecifier" && source.startsWith("effect/")) {
    return source.slice("effect/".length);
  }
  return undefined;
};

// A base such as `Schema.TaggedClass<Self>()("Tag", fields)` is its constructor `Schema.TaggedClass`, called.
const constructorOf = (base: ESTree.Expression): ESTree.Expression =>
  base.type === "CallExpression" ? constructorOf(base.callee) : base;

const isEffectBase = (context: Context, node: ESTree.Class): boolean => {
  if (node.superClass === null) {
    return false;
  }
  const base = constructorOf(node.superClass);
  if (
    base.type !== "MemberExpression" ||
    base.computed ||
    base.object.type !== "Identifier" ||
    base.property.type !== "Identifier"
  ) {
    return false;
  }
  const variable = lookup(context.sourceCode.getScope(node), base.object.name);
  const module = effectModule(variable);
  return module !== undefined && (bases.get(module)?.has(base.property.name) ?? false);
};

export const noPlainClass: Readonly<Rule> = {
  create: (context) => {
    const check = (node: ESTree.Class): void => {
      if (!isEffectBase(context, node)) {
        context.report({ messageId: "plain", node });
      }
    };
    return { ClassDeclaration: check, ClassExpression: check };
  },
  meta: {
    docs: {
      description:
        "Allow a class only when it extends a Schema, Data or Context class imported from effect.",
    },
    messages: {
      plain:
        "Plain class: extend Schema.Class, Schema.TaggedClass, Schema.TaggedError, a Data class or a Context service from effect, or use a plain value.",
    },
    type: "problem",
  },
};
