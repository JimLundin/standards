// The kinds of syntax that decide what is counted; every other node is "other".
type Kind =
  | "and"
  | "binary"
  | "call"
  | "case"
  | "cases"
  | "class"
  | "closure"
  | "coalesce"
  | "conditional"
  | "constructor"
  | "export"
  | "function"
  | "identifier"
  | "if"
  | "loop"
  | "member"
  | "or"
  | "other"
  | "property"
  | "switch"
  | "variable";

// A node of a source file's syntax tree, with its children in source order. An identifier's name is its text, and every other node's is "".
interface Syntax {
  readonly kind: Kind;
  readonly name: string;
  readonly line: number;
  readonly children: ReadonlyArray<Syntax>;
}

export type { Kind, Syntax };
