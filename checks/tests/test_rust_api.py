import json
from typing import TYPE_CHECKING

from ordered import FrozenList, FrozenOrderedDict

from checks.core.rust_api import documents, request, run
from checks.core.values import Inputs, Request, parse_json

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

ONLY_DATA = "; the core's public API takes only data"
PATHS = json.dumps({
    "1": {"path": ["demo", "Store"], "crate_id": 0},
    "2": {"path": ["core", "clone", "Clone"], "crate_id": 1},
    "3": {"path": ["core", "ops", "function", "Fn"], "crate_id": 1},
    "4": {
        "path": ["core", "iter", "traits", "iterator", "Iterator"],
        "crate_id": 1,
    },
    "5": {"path": ["core", "convert", "From"], "crate_id": 1},
    "9": {"path": [1, 2], "crate_id": 1},
})


def node(**fields: object) -> object:
    return fields


POINTER = node(function_pointer=node())


def bound(trait: str, path: str = "", args: object = None) -> object:
    return node(trait_bound=node(trait=node(id=trait, path=path, args=args)))


def dyn(*traits: str) -> object:
    return node(
        dyn_trait=node(traits=[node(trait=node(id=trait)) for trait in traits])
    )


def generics(*params: object, where: Sequence[object] = ()) -> object:
    return node(params=list(params), where_predicates=list(where))


def param(name: str, *bounds: object) -> object:
    return node(name=name, kind=node(type=node(bounds=list(bounds))))


def span(line: int, filename: str = "core/src/lib.rs") -> object:
    return node(filename=filename, begin=[line, 1])


def function(
    name: str,
    at: object,
    inputs: Sequence[object] = (),
    types: object = None,
    *,
    is_async: bool = False,
) -> object:
    signature = node(inputs=[["x", kind] for kind in inputs], output=dyn())
    details = node(
        sig=signature,
        generics=types or generics(),
        header=node(is_async=is_async),
    )
    return node(crate_id=0, name=name, span=at, inner=node(function=details))


def item(name: str | None, line: int, **inner: object) -> object:
    return node(crate_id=0, name=name, span=span(line), inner=inner)


def implementation(
    line: int, items: Sequence[str] = (), **details: object
) -> object:
    return item(
        None,
        line,
        impl={"generics": generics(), "items": list(items), **details},
    )


def document(index: Mapping[str, object], version: int = 61) -> str:
    return json.dumps(
        node(format_version=version, index=dict(index), paths=parse_json(PATHS))
    )


METADATA = json.dumps({
    "target_directory": "C:\\work\\target",
    "packages": [
        {
            "name": "demo-core",
            "targets": [{"name": "demo-core", "kind": ["lib"]}],
        },
        {"name": "io", "targets": [{"name": "io", "kind": ["rlib", "cdylib"]}]},
        {"name": "app", "targets": [{"name": "app", "kind": ["bin"]}]},
    ],
})
DOC = "C:/work/target/doc/demo_core.json"


def check(
    index: Mapping[str, object], *skips: str, version: int = 61
) -> FrozenList[str]:
    texts = FrozenOrderedDict({
        "m.json": METADATA,
        DOC: document(index, version),
    })
    return run((*skips, "m.json", "demo-core"), Inputs(texts)).lines


def test_documents_for_the_named_library_packages() -> None:
    assert documents(parse_json(METADATA), ("demo-core", "io", "app")) == (
        DOC,
        "C:/work/target/doc/io.json",
    )


def test_request_reads_metadata_first() -> None:
    assert request(("--skip=x", "m.json", "demo-core"), Inputs()) == Request(
        FrozenList(("m.json",))
    )
    texts = FrozenOrderedDict({"m.json": METADATA})
    assert request(("m.json", "demo-core"), Inputs(texts)) == Request(
        FrozenList(("m.json", DOC))
    )


def test_data_only_api_passes() -> None:
    vector = node(
        resolved_path=node(
            path="Vec",
            args=node(
                angle_bracketed=node(args=[node(type=node(primitive="u8"))])
            ),
        )
    )
    index = {
        "10": function("plain", span(3), [vector]),
        "11": function(
            "cloned",
            span(4),
            [node(generic="T")],
            generics(param("T", bound("2"))),
        ),
        "12": node(
            crate_id=1,
            name="foreign",
            inner=node(function=node(header=node(is_async=True))),
        ),
    }
    assert check(index) == ("All checks passed",)


def test_every_way_to_hand_the_core_an_effect() -> None:
    callback = node(
        impl_trait=[bound("3", args=node(parenthesized=node(inputs=[POINTER])))]
    )
    lines_bound = node(bound_predicate=node(bounds=[bound("4")]))
    index = {
        "20": function(
            "port",
            span(5),
            [node(generic="S")],
            generics(param("S", bound("1"))),
        ),
        "21": function(
            "dyn_port", span(6), [node(borrowed_ref=node(type=dyn("1", "2")))]
        ),
        "22": function("callback", span(7), [callback]),
        "23": function("pointer", span(8), [POINTER]),
        "24": function("later", span(9), is_async=True),
        "25": function("lines", span(10), (), generics(where=[lines_bound])),
        "26": function(
            "unknown",
            span(11),
            [node(impl_trait=[bound("99", path="Mystery")])],
        ),
        "27": function(
            "odd", span(12), [node(impl_trait=[bound("9", path="Odd")])]
        ),
        "30": item("clock", 13, struct_field=POINTER),
        "31": item(
            "Engine", 14, struct=node(generics=generics(param("S", bound("1"))))
        ),
        "32": node(
            crate_id=0,
            name="Clock",
            span=span(2, "core/src/types.rs"),
            inner=node(type_alias=node(generics=generics(), type=POINTER)),
        ),
    }
    assert check(index) == (
        f"core/src/lib.rs:5: `port` is bounded by `demo::Store`{ONLY_DATA}",
        f"core/src/lib.rs:6: `dyn_port` takes a trait object `dyn demo::Store, core::clone::Clone`{ONLY_DATA}",
        f"core/src/lib.rs:7: `callback` is bounded by `core::ops::function::Fn`{ONLY_DATA}",
        f"core/src/lib.rs:7: `callback` takes a function pointer{ONLY_DATA}",
        f"core/src/lib.rs:8: `pointer` takes a function pointer{ONLY_DATA}",
        f"core/src/lib.rs:9: `later` is async{ONLY_DATA}",
        f"core/src/lib.rs:10: `lines` is bounded by `core::iter::traits::iterator::Iterator`{ONLY_DATA}",
        f"core/src/lib.rs:11: `unknown` is bounded by `Mystery`{ONLY_DATA}",
        f"core/src/lib.rs:12: `odd` is bounded by `Odd`{ONLY_DATA}",
        f"core/src/lib.rs:13: `clock` takes a function pointer{ONLY_DATA}",
        f"core/src/lib.rs:14: `Engine` is bounded by `demo::Store`{ONLY_DATA}",
        f"core/src/types.rs:2: `Clock` takes a function pointer{ONLY_DATA}",
        "Found 12 issues",
    )


def test_impls() -> None:
    boxed_fn = node(angle_bracketed=node(args=[node(type=dyn("3"))]))
    index = {
        "1": item("Store", 19, trait=node(generics=generics())),
        "40": implementation(20, ("41",), trait=node(id="5", args=boxed_fn)),
        "41": function("from", span(21), [dyn()]),
        "42": implementation(22, generics=generics(param("I", bound("4")))),
        "43": implementation(
            23,
            ("44",),
            is_synthetic=True,
            generics=generics(param("T", bound("4"))),
        ),
        "44": function("synthetic_method", span(24), [POINTER]),
        "45": implementation(
            25,
            ("46",),
            blanket_impl=node(generic="T"),
            generics=generics(param("T", bound("4"))),
        ),
        "46": function("blanket_method", span(26), [POINTER]),
        "47": implementation(27, ("48",), trait=node(id="1")),
        "48": function("load", span(28), [POINTER]),
        "50": node(
            crate_id=1, inner=node(impl=node(trait=node(id="2"), items=["51"]))
        ),
        "51": function("not_foreign_impl_member", span(29), [POINTER]),
    }
    assert check(index) == (
        f"core/src/lib.rs:20: `impl` takes a trait object `dyn core::ops::function::Fn`{ONLY_DATA}",
        f"core/src/lib.rs:22: `impl` is bounded by `core::iter::traits::iterator::Iterator`{ONLY_DATA}",
        f"core/src/lib.rs:28: `load` takes a function pointer{ONLY_DATA}",
        f"core/src/lib.rs:29: `not_foreign_impl_member` takes a function pointer{ONLY_DATA}",
        "Found 4 issues",
    )


def test_findings_are_deduplicated_and_sorted() -> None:
    index = {
        "60": function("z", span(1, "b.rs"), [POINTER, POINTER]),
        "61": function("a", span(9), [POINTER]),
        "62": function("b", span(3), [POINTER]),
        "63": function("y", span(3), [POINTER]),
    }
    assert check(index)[:-1] == (
        f"b.rs:1: `z` takes a function pointer{ONLY_DATA}",
        f"core/src/lib.rs:3: `b` takes a function pointer{ONLY_DATA}",
        f"core/src/lib.rs:3: `y` takes a function pointer{ONLY_DATA}",
        f"core/src/lib.rs:9: `a` takes a function pointer{ONLY_DATA}",
    )


def test_missing_spans_and_names() -> None:
    index = {
        "70": node(crate_id=0, inner=node(struct_field=POINTER)),
        "71": node(
            crate_id=0,
            name="x",
            span=node(filename="a.rs", begin=["1"]),
            inner=node(struct_field=POINTER),
        ),
        "72": node(
            crate_id=0,
            name="y",
            span=node(filename="a.rs", begin=[]),
            inner=node(struct_field=POINTER),
        ),
    }
    assert check(index)[:-1] == (
        f"?:0: `impl` takes a function pointer{ONLY_DATA}",
        f"a.rs:0: `x` takes a function pointer{ONLY_DATA}",
        f"a.rs:0: `y` takes a function pointer{ONLY_DATA}",
    )


def test_skips_by_path() -> None:
    index = {
        "80": function("a", span(1), [POINTER]),
        "81": function("b", span(2, "core/src/other.rs"), [POINTER]),
    }
    assert check(index, "--skip=core/src/lib.rs") == (
        f"core/src/other.rs:2: `b` takes a function pointer{ONLY_DATA}",
        "Found 1 issues",
    )


def test_untested_format() -> None:
    assert check({}, version=62) == (
        f"rust_api.py:0: rustdoc JSON format 62 is untested; check rust_api.py against it and add it to FORMATS{ONLY_DATA}",
        "Found 1 issues",
    )
