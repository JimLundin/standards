import type { Rule } from "@oxlint/plugins";

const collections: ReadonlySet<string> = new Set([
	"Array",
	"Map",
	"Set",
	"WeakMap",
	"WeakSet",
]);

export const readonlyTypes: Readonly<Rule> = {
	create: (context) => ({
		TSArrayType: (node): void => {
			const { parent } = node;
			if (parent.type !== "TSTypeOperator" || parent.operator !== "readonly") {
				context.report({ messageId: "mutable", node });
			}
		},
		TSTypeReference: (node): void => {
			if (
				node.typeName.type === "Identifier" &&
				collections.has(node.typeName.name)
			) {
				context.report({ messageId: "mutable", node });
			}
		},
	}),
	meta: {
		docs: { description: "Require readonly collection types." },
		messages: {
			mutable:
				"Mutable collection type: use readonly T[], ReadonlyArray, ReadonlyMap or ReadonlySet.",
		},
		type: "problem",
	},
};
