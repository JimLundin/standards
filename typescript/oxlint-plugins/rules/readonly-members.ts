import type { ESTree, Rule } from "@oxlint/plugins";

type Member = ESTree.AccessorProperty | ESTree.PropertyDefinition | ESTree.TSPropertySignature;

export const readonlyMembers: Readonly<Rule> = {
  create: (context) => {
    const check = (node: Member): void => {
      if (node.readonly !== true) {
        context.report({ messageId: "mutable", node });
      }
    };
    return {
      PropertyDefinition: check,
      TSAbstractPropertyDefinition: check,
      TSPropertySignature: check,
    };
  },
  meta: {
    docs: {
      description: "Require class properties and type members to be readonly.",
    },
    messages: {
      mutable: "Mutable property: mark it readonly and return a new value instead.",
    },
    type: "problem",
  },
};
