import type { Rule } from "@oxlint/plugins";

export const noThrow: Readonly<Rule> = {
  create: (context) => ({
    ThrowStatement: (node): void => {
      context.report({ messageId: "throw", node });
    },
  }),
  meta: {
    docs: { description: "Forbid throw statements." },
    messages: {
      throw:
        "throw: fail with a Data.TaggedError through Effect.fail, so the error is in the Effect's type.",
    },
    type: "problem",
  },
};
