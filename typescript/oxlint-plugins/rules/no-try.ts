import type { Rule } from "@oxlint/plugins";

export const noTry: Readonly<Rule> = {
	create: (context) => ({
		TryStatement: (node): void => {
			context.report({ messageId: "try", node });
		},
	}),
	meta: {
		docs: { description: "Forbid try statements." },
		messages: {
			try: "try/catch: handle an Effect's typed errors with Effect.catchTag, Effect.ensuring or Effect.acquireRelease, and wrap code that throws in Effect.try.",
		},
		type: "problem",
	},
};
