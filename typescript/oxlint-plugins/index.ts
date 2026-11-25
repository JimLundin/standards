import type { Plugin } from "@oxlint/plugins";
import { noModuleState } from "./rules/no-module-state.ts";
import { noPlainClass } from "./rules/no-plain-class.ts";
import { noThrow } from "./rules/no-throw.ts";
import { noTry } from "./rules/no-try.ts";
import { readonlyMembers } from "./rules/readonly-members.ts";
import { readonlyTypes } from "./rules/readonly-types.ts";

const standards: Readonly<Plugin> = {
  meta: { name: "standards" },
  rules: {
    "no-module-state": noModuleState,
    "no-plain-class": noPlainClass,
    "no-throw": noThrow,
    "no-try": noTry,
    "readonly-members": readonlyMembers,
    "readonly-types": readonlyTypes,
  },
};

export default standards;
