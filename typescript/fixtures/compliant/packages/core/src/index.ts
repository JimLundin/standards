import { Schema } from "effect";

const Greeting = Schema.Struct({ name: Schema.String });

type Greeting = typeof Greeting.Type;

const GreetingJson = Schema.fromJsonString(Greeting);

const greet = (greeting: Greeting): string => `Hello, ${greeting.name}`;

export { Greeting, GreetingJson, greet };
