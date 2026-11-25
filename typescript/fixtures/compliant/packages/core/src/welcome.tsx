import type { Greeting } from "./index.ts";
import type { ReactElement } from "react";
import { greet } from "./index.ts";

export const Welcome = (greeting: Greeting): ReactElement => <p>{greet(greeting)}</p>;
