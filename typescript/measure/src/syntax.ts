import type { Kind, Syntax } from "@standards/measure-core";
import type { Node, SourceFile } from "typescript/unstable/ast";
import { isIdentifier, isPrivateIdentifier } from "typescript/unstable/ast/is";
import { SyntaxKind } from "typescript/unstable/ast";

const LINE_BASE = 1;
const KINDS: ReadonlyMap<SyntaxKind, Kind> = new Map([
  [SyntaxKind.AmpersandAmpersandToken, "and"],
  [SyntaxKind.ArrowFunction, "closure"],
  [SyntaxKind.BarBarToken, "or"],
  [SyntaxKind.BinaryExpression, "binary"],
  [SyntaxKind.CallExpression, "call"],
  [SyntaxKind.CaseBlock, "cases"],
  [SyntaxKind.CaseClause, "case"],
  [SyntaxKind.ClassDeclaration, "class"],
  [SyntaxKind.ClassExpression, "class"],
  [SyntaxKind.ConditionalExpression, "conditional"],
  [SyntaxKind.Constructor, "constructor"],
  [SyntaxKind.DefaultClause, "case"],
  [SyntaxKind.DoStatement, "loop"],
  [SyntaxKind.ExportAssignment, "export"],
  [SyntaxKind.ForInStatement, "loop"],
  [SyntaxKind.ForOfStatement, "loop"],
  [SyntaxKind.ForStatement, "loop"],
  [SyntaxKind.FunctionDeclaration, "function"],
  [SyntaxKind.FunctionExpression, "closure"],
  [SyntaxKind.GetAccessor, "member"],
  [SyntaxKind.Identifier, "identifier"],
  [SyntaxKind.IfStatement, "if"],
  [SyntaxKind.MethodDeclaration, "member"],
  [SyntaxKind.PrivateIdentifier, "identifier"],
  [SyntaxKind.PropertyAccessExpression, "property"],
  [SyntaxKind.PropertyDeclaration, "member"],
  [SyntaxKind.QuestionQuestionToken, "coalesce"],
  [SyntaxKind.SetAccessor, "member"],
  [SyntaxKind.SwitchStatement, "switch"],
  [SyntaxKind.VariableDeclaration, "variable"],
  [SyntaxKind.WhileStatement, "loop"],
]);

const childrenOf = (node: Node): ReadonlyArray<Node> => {
  const children: Array<Node> = [];
  node.forEachChild((child) => {
    children.push(child);
  });
  return children;
};

const nameOf = (node: Node): string =>
  isIdentifier(node) || isPrivateIdentifier(node) ? node.text : "";

const converted = (file: SourceFile, node: Node): Syntax => ({
  children: childrenOf(node).map((child) => converted(file, child)),
  kind: KINDS.get(node.kind) ?? "other",
  line: file.getLineAndCharacterOfPosition(node.getStart(file)).line + LINE_BASE,
  name: nameOf(node),
});

// A source file's syntax tree, as the core reads it.
const syntaxOf = (file: SourceFile): Syntax => converted(file, file);

export { syntaxOf };
