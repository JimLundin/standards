import { Schema } from "effect";

export const Greeting = Schema.Struct({ name: Schema.String });

export type Greeting = typeof Greeting.Type;

export const greet = (greeting: Greeting): string => `Hello, ${greeting.name}`;
