export interface Greeting {
  readonly name: string;
}

export const greet = (greeting: Greeting): string => `Hello, ${greeting.name}`;
