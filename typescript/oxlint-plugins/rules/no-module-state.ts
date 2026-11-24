import type { Context, ESTree, Rule } from "@oxlint/plugins";

const collections: ReadonlySet<string> = new Set(["Array", "Map", "Set", "WeakMap", "WeakSet"]);
const readonlyTypes: ReadonlySet<string> = new Set([
  "Readonly",
  "ReadonlyArray",
  "ReadonlyMap",
  "ReadonlySet",
]);

// A binding outside every function is state that the module's functions share.
const atModuleLevel = (context: Context, node: ESTree.Node): boolean => {
  const { type } = context.sourceCode.getScope(node).variableScope;
  return type === "module" || type === "global";
};

const isReadonlyType = (annotation: ESTree.TSTypeAnnotation | null | undefined): boolean => {
  const type = annotation?.typeAnnotation;
  if (type?.type === "TSTypeOperator") {
    return type.operator === "readonly";
  }
  return (
    type?.type === "TSTypeReference" &&
    type.typeName.type === "Identifier" &&
    readonlyTypes.has(type.typeName.name)
  );
};

const isMutable = (context: Context, value: ESTree.Expression | null): boolean => {
  switch (value?.type) {
    case "ArrayExpression":
    case "ObjectExpression": {
      return true;
    }
    case "NewExpression": {
      return (
        value.callee.type === "Identifier" &&
        collections.has(value.callee.name) &&
        context.sourceCode.isGlobalReference(value.callee)
      );
    }
    case "TSAsExpression": {
      const { typeAnnotation } = value;
      const constant =
        typeAnnotation.type === "TSTypeReference" &&
        typeAnnotation.typeName.type === "Identifier" &&
        typeAnnotation.typeName.name === "const";
      return !constant && isMutable(context, value.expression);
    }
    case "TSSatisfiesExpression": {
      return isMutable(context, value.expression);
    }
    default: {
      return false;
    }
  }
};

export const noModuleState: Readonly<Rule> = {
  create: (context) => ({
    VariableDeclaration: (node): void => {
      if (node.declare === true || !atModuleLevel(context, node)) {
        return;
      }
      if (node.kind === "let" || node.kind === "var") {
        context.report({ messageId: "binding", node });
        return;
      }
      for (const declarator of node.declarations) {
        if (!isReadonlyType(declarator.id.typeAnnotation) && isMutable(context, declarator.init)) {
          context.report({ messageId: "collection", node: declarator });
        }
      }
    },
  }),
  meta: {
    docs: { description: "Forbid mutable state at module level." },
    messages: {
      binding: "Mutable module-level binding: use const, or keep it inside a function.",
      collection:
        "Mutable module-level collection: use as const, a readonly type, or keep it inside a function.",
    },
    type: "problem",
  },
};
