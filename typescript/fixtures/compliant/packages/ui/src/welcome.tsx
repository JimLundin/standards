import { AsyncResult } from "effect/reactivity";
import type { ReactElement } from "react";
import { greeting } from "./greeting.ts";
import { useAtomValue } from "@effect/atom-react";

export const Welcome = (): ReactElement => (
  <p>{AsyncResult.getOrElse(useAtomValue(greeting), () => "")}</p>
);
