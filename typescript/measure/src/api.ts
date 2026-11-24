import type { Checker, Symbol as Named, Project, Type } from "typescript/unstable/sync";
import type { Export, Look, Origin, Part, Placement, Plan, Shape } from "@standards/measure-core";
import type { Node, SourceFile } from "typescript/unstable/ast";
import {
  apiRecords,
  declaredHere,
  isAlias,
  isMethod,
  partsOf,
  plan,
  readsMembers,
} from "@standards/measure-core";
import { SignatureKind } from "typescript/unstable/sync";
import { SyntaxKind } from "typescript/unstable/ast";
import { isClassDeclaration } from "typescript/unstable/ast/is";

const LINE_BASE = 1;
const FIRST = 0;
const NO_FLAGS = 0;
const DATA: Readonly<Shape> = { kind: "data" };

// Where the checker reads types: the types it's reading inside, so that a recursive type ends, and whether it's at an export's own type.
interface Reader {
  readonly project: Project;
  readonly checker: Checker;
  readonly inside: ReadonlyArray<number>;
  readonly top: boolean;
}

// A type, with what was first read of it.
interface Looked {
  readonly type: Type;
  readonly look: Look;
}

type Recurse = (reader: Reader, type: Type) => Shape;

type ReadOf = (reader: Reader, looked: Looked, recurse: Recurse) => Shape;

const defined = <Value>(values: ReadonlyArray<Value | undefined>): ReadonlyArray<Value> =>
  values.filter((value) => value !== undefined);

// A symbol, with the path of its first declaration.
const originOf = (symbol: Named): Origin => ({
  name: symbol.name,
  path: symbol.declarations
    .slice(FIRST, FIRST + LINE_BASE)
    .map((declaration) => declaration.path)
    .join(""),
});

const originsOf = (type: Type): ReadonlyArray<Origin> =>
  defined([type.getAliasSymbol(), type.getSymbol()]).map((symbol) => originOf(symbol));

const lookOf = (checker: Checker, type: Type): Look => ({
  calls: checker.getSignaturesOfType(type, SignatureKind.Call).length,
  constructs: checker.getSignaturesOfType(type, SignatureKind.Construct).length,
  flags: type.flags,
  id: type.id,
  origins: originsOf(type),
  symbolFlags: type.getSymbol()?.flags ?? NO_FLAGS,
  tuple: checker.isTupleType(type),
});

const within = (reader: Reader, type: Type): Reader => ({
  ...reader,
  inside: [...reader.inside, type.id],
  top: false,
});

const argumentsOf = (checker: Checker, type: Type): ReadonlyArray<Type> => [
  ...type.getAliasTypeArguments(),
  ...(type.isTypeReference() ? checker.getTypeArguments(type) : []),
];

// A union's or an intersection's constituents, or an object's properties' and index signatures' types.
const membersOf = (checker: Checker, type: Type): ReadonlyArray<Type> =>
  type.isUnionType() || type.isIntersectionType()
    ? type.getTypes()
    : [
        ...defined(checker.getTypeOfSymbol(checker.getPropertiesOfType(type))),
        ...checker.getIndexInfosOfType(type).map((info) => info.valueType),
      ];

// The types of the parameters and returns of each call and construct signature.
const signaturePartsOf = (checker: Checker, type: Type): ReadonlyArray<Type> =>
  [SignatureKind.Call, SignatureKind.Construct]
    .flatMap((kind) => checker.getSignaturesOfType(type, kind))
    .flatMap((signature) =>
      defined([
        ...checker.getTypeOfSymbol(signature.getParameters()),
        checker.getReturnTypeOfSignature(signature),
      ]),
    );

// The expression a class declaration extends.
const heritageOf = (project: Project, symbol: Named): ReadonlyArray<Node> =>
  defined([symbol.valueDeclaration?.resolve(project)])
    .filter((node) => isClassDeclaration(node))
    .flatMap((declaration) => declaration.heritageClauses ?? [])
    .flatMap((clause) =>
      clause.token === SyntaxKind.ExtendsKeyword ? clause.types.map((type) => type.expression) : [],
    );

// A class, by the origins of the class it extends, its methods and its other properties' types.
const classOf = (reader: Reader, symbol: Named, recurse: Recurse): Shape => {
  const { checker } = reader;
  const bases = defined(
    heritageOf(reader.project, symbol).map((node) => checker.getTypeAtLocation(node)),
  ).flatMap((type) => originsOf(type));
  const instance = checker.getDeclaredTypeOfSymbol(symbol);
  const properties = readsMembers(bases) ? checker.getPropertiesOfType(instance) : [];
  const fields = properties.filter((property) => !isMethod(property.flags));
  return {
    bases,
    kind: "class",
    members: defined(checker.getTypeOfSymbol(fields)).map((type) =>
      recurse(within(reader, instance), type),
    ),
    methods: properties
      .filter((property) => isMethod(property.flags))
      .map((property) => property.name),
  };
};

const typed = (
  { origins }: Look,
  parts: ReadonlyArray<Shape>,
  members: ReadonlyArray<Shape>,
): Shape => ({ arguments: parts, kind: "type", members, origins });

const READERS: Readonly<Record<Plan, ReadOf>> = {
  arguments: (reader, { look, type }, recurse) =>
    typed(
      look,
      argumentsOf(reader.checker, type).map((part) => recurse(within(reader, type), part)),
      [],
    ),
  class: (reader, { type }, recurse) =>
    defined([type.getSymbol()])
      .map((symbol) => classOf(reader, symbol, recurse))
      .at(FIRST) ?? DATA,
  data: () => DATA,
  function: (reader, { type }) => ({
    kind: "function",
    parts: [],
    text: reader.checker.typeToString(type),
  }),
  members: (reader, { look, type }, recurse) =>
    typed(
      look,
      argumentsOf(reader.checker, type).map((part) => recurse(within(reader, type), part)),
      membersOf(reader.checker, type).map((member) => recurse(within(reader, type), member)),
    ),
  named: (_reader, { look }) => typed(look, [], []),
  signatures: (reader, { type }, recurse) => ({
    kind: "function",
    parts: signaturePartsOf(reader.checker, type).map((part) =>
      recurse(within(reader, type), part),
    ),
    text: reader.checker.typeToString(type),
  }),
};

// A type as the core judges it, read as far as the core plans.
const shapeOf = (reader: Reader, type: Type): Shape => {
  const look = lookOf(reader.checker, type);
  return READERS[plan(look, reader.inside, reader.top)](reader, { look, type }, shapeOf);
};

const PARTS: Readonly<Record<Part, (reader: Reader, symbol: Named) => ReadonlyArray<Shape>>> = {
  class: (reader, symbol) => [classOf(reader, symbol, shapeOf)],
  type: (reader, symbol) => [shapeOf(reader, reader.checker.getDeclaredTypeOfSymbol(symbol))],
  value: (reader, symbol) =>
    defined([reader.checker.getTypeOfSymbol(symbol)]).map((type) => shapeOf(reader, type)),
};

const lineOf = (project: Project, file: SourceFile, symbol: Named): number =>
  defined([symbol.declarations.at(FIRST)?.resolve(project)])
    .map((node) => file.getLineAndCharacterOfPosition(node.getStart(file)).line + LINE_BASE)
    .at(FIRST) ?? LINE_BASE;

const targetOf = (checker: Checker, symbol: Named): Named =>
  isAlias(symbol.flags) ? checker.getAliasedSymbol(symbol) : symbol;

// The exports declared in a source file, or re-exported from a dependency; another of the project's files is judged on its own.
const exportsOf = (project: Project, file: SourceFile): ReadonlyArray<Export> => {
  const { checker } = project;
  const reader = { checker, inside: [], project, top: true };
  return defined([checker.getSymbolAtLocation(file)])
    .flatMap((module) => checker.getExportsOfModule(module))
    .flatMap((symbol) => {
      const target = targetOf(checker, symbol);
      return declaredHere(file.fileName, originOf(target).path)
        ? [
            {
              line: lineOf(project, file, symbol),
              name: symbol.name,
              shapes: partsOf(target.flags).flatMap((part) => PARTS[part](reader, target)),
            },
          ]
        : [];
    });
};

// The api records of a core file's exports.
const api = (project: Project, file: SourceFile, placement: Placement): ReadonlyArray<string> =>
  placement.layer === "core"
    ? exportsOf(project, file).flatMap((found) => apiRecords(placement, found))
    : [];

export { api };
