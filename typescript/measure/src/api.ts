import type { Checker, Project, Symbol as Named, Type } from "typescript/unstable/sync";
import type { Export, Origin, Placement, Shape } from "@standards/measure-core";
import type { Node, SourceFile } from "typescript/unstable/ast";
import { SignatureKind, SymbolFlags, TypeFlags } from "typescript/unstable/sync";
import { apiRecords, declaredHere, reading } from "@standards/measure-core";
import { SyntaxKind } from "typescript/unstable/ast";
import { isClassDeclaration } from "typescript/unstable/ast/is";

const LINE_BASE = 1;
const DATA: Shape = { kind: "data" };
const STRUCTURED = TypeFlags.Object | TypeFlags.Union | TypeFlags.Intersection;
const TYPES = SymbolFlags.TypeAlias | SymbolFlags.Interface;

// A type the checker reads, with the types it's being read inside, so that a recursive type ends.
interface Reader {
  readonly checker: Checker;
  readonly inside: ReadonlySet<number>;
}

const originOf = (symbol: Named): Origin => ({
  name: symbol.name,
  path: symbol.declarations[0]?.path ?? "",
});

const originsOf = (type: Type): ReadonlyArray<Origin> =>
  [type.getAliasSymbol(), type.getSymbol()]
    .filter((symbol) => symbol !== undefined)
    .map(originOf);

const defined = <Value>(values: ReadonlyArray<Value | undefined>): ReadonlyArray<Value> =>
  values.filter((value) => value !== undefined);

// The types of a signature's parameters and returns, for each call and construct signature of `type`.
const partsOf = ({ checker }: Reader, type: Type): ReadonlyArray<Type> =>
  [SignatureKind.Call, SignatureKind.Construct]
    .flatMap((kind) => checker.getSignaturesOfType(type, kind))
    .flatMap((signature) =>
      defined([
        ...checker.getTypeOfSymbol(signature.getParameters()),
        checker.getReturnTypeOfSignature(signature),
      ]),
    );

const membersOf = ({ checker }: Reader, type: Type): ReadonlyArray<Type> => [
  ...(type.getTypes() ?? []),
  ...defined(checker.getTypeOfSymbol(checker.getPropertiesOfType(type))),
  ...checker.getIndexInfosOfType(type).map((info) => info.valueType),
];

const argumentsOf = ({ checker }: Reader, type: Type): ReadonlyArray<Type> => [
  ...type.getAliasTypeArguments(),
  ...(type.isTypeReference() ? checker.getTypeArguments(type) : []),
];

// A structured type, read as far as the core reads one of its origins.
const structured = (reader: Reader, type: Type): Shape => {
  const origins = originsOf(type);
  const read = reading(origins);
  const inner = { ...reader, inside: new Set([...reader.inside, type.id]) };
  const parts = partsOf(reader, type);
  if (read !== "all" || reader.checker.isTupleType(type)) {
    const shapes = read === "none" ? [] : argumentsOf(reader, type).map((t) => shapeOf(inner, t));
    return { arguments: shapes, kind: "type", members: [], origins };
  }
  return parts.length > 0
    ? { kind: "function", parts: parts.map((t) => shapeOf(inner, t)), text: reader.checker.typeToString(type) }
    : {
        arguments: argumentsOf(reader, type).map((t) => shapeOf(inner, t)),
        kind: "type",
        members: membersOf(reader, type).map((t) => shapeOf(inner, t)),
        origins,
      };
};

// A type as the core judges it; anything but an object, a union or an intersection is data.
const shapeOf = (reader: Reader, type: Type): Shape =>
  (type.flags & STRUCTURED) === 0 || reader.inside.has(type.id) ? DATA : structured(reader, type);

const extended = (project: Project, symbol: Named): Node | undefined => {
  const declaration = symbol.valueDeclaration?.resolve(project);
  return declaration !== undefined && isClassDeclaration(declaration)
    ? declaration.heritageClauses
        ?.find((clause) => clause.token === SyntaxKind.ExtendsKeyword)
        ?.types.at(0)?.expression
    : undefined;
};

// A class, by the origins of the class it extends, its methods and its other properties' types.
const classOf = (reader: Reader, project: Project, symbol: Named): Shape => {
  const base = extended(project, symbol);
  const baseType = base === undefined ? undefined : reader.checker.getTypeAtLocation(base);
  const bases = baseType === undefined ? [] : originsOf(baseType);
  const properties =
    reading(bases) === "all"
      ? reader.checker.getPropertiesOfType(reader.checker.getDeclaredTypeOfSymbol(symbol))
      : [];
  const isMethod = (property: Named): boolean => (property.flags & SymbolFlags.Method) !== 0;
  return {
    bases,
    kind: "class",
    members: defined(
      reader.checker.getTypeOfSymbol(properties.filter((property) => !isMethod(property))),
    ).map((type) => shapeOf(reader, type)),
    methods: properties.filter(isMethod).map((property) => property.name),
  };
};

// The shapes of a symbol's value and its type.
const shapesOf = (reader: Reader, project: Project, symbol: Named): ReadonlyArray<Shape> => {
  const { checker } = reader;
  if ((symbol.flags & SymbolFlags.Class) !== 0) {
    return [classOf(reader, project, symbol)];
  }
  const value = (symbol.flags & SymbolFlags.Value) === 0 ? undefined : checker.getTypeOfSymbol(symbol);
  const declared = (symbol.flags & TYPES) === 0 ? undefined : checker.getDeclaredTypeOfSymbol(symbol);
  return defined([value, declared]).map((type) => shapeOf(reader, type));
};

const lineOf = (project: Project, file: SourceFile, symbol: Named): number => {
  const node = symbol.declarations[0]?.resolve(project);
  return node === undefined
    ? LINE_BASE
    : file.getLineAndCharacterOfPosition(node.getStart(file)).line + LINE_BASE;
};

const targetOf = (checker: Checker, symbol: Named): Named =>
  (symbol.flags & SymbolFlags.Alias) === 0 ? symbol : checker.getAliasedSymbol(symbol);

// The exports declared in a source file, or re-exported from a dependency; another of the project's files is judged on its own.
const exportsOf = (project: Project, file: SourceFile): ReadonlyArray<Export> => {
  const { checker } = project;
  const module = checker.getSymbolAtLocation(file);
  const reader = { checker, inside: new Set<number>() };
  return (module === undefined ? [] : checker.getExportsOfModule(module))
    .map((symbol) => ({ symbol, target: targetOf(checker, symbol) }))
    .filter(({ target }) => declaredHere(file.fileName, originOf(target).path))
    .map(({ symbol, target }) => ({
      line: lineOf(project, file, symbol),
      name: symbol.name,
      shapes: shapesOf(reader, project, target),
    }));
};

// The api records of a core file's exports.
const api = (project: Project, file: SourceFile, placement: Placement): ReadonlyArray<string> =>
  placement.layer === "core"
    ? exportsOf(project, file).flatMap((found) => apiRecords(placement, found))
    : [];

export { api };
