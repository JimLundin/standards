import type { Plugin } from "@oxlint/plugins";
import { noModuleState } from "./rules/no-module-state.ts";
import { noPlainClass } from "./rules/no-plain-class.ts";
import { readonlyMembers } from "./rules/readonly-members.ts";
import { readonlyTypes } from "./rules/readonly-types.ts";

// The standard's own rules, one module each in rules/; the standard's config turns each on.
const standards: Readonly<Plugin> = {
  meta: { name: "standards" },
  rules: {
    "no-module-state": noModuleState,
    "no-plain-class": noPlainClass,
    "readonly-members": readonlyMembers,
    "readonly-types": readonlyTypes,
  },
};

export default standards;
