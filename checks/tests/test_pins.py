import tomllib
from pathlib import Path

from checks.core.units import pins_of
from checks.core.values import parse_json

STANDARDS = Path(__file__).resolve().parents[2]


def test_rust_decisions_is_pinned_at_the_version_of_rust_measure() -> None:
    pins = pins_of((STANDARDS / "tools.env").read_text(encoding="utf-8"))
    manifest = tomllib.loads(
        (STANDARDS / "rust/measure/Cargo.toml").read_text(encoding="utf-8")
    )
    assert pins["RUST_DECISIONS"] == manifest["package"]["version"]


def test_ts_measure_is_pinned_at_the_version_of_typescript_measure() -> None:
    pins = pins_of((STANDARDS / "tools.env").read_text(encoding="utf-8"))
    manifest = parse_json(
        (STANDARDS / "typescript/measure/package.json").read_text(
            encoding="utf-8"
        )
    )
    assert pins["TS_MEASURE"] == manifest.get("version")


def test_pins_are_the_name_and_version_lines() -> None:
    text = "# NODE=1\nNODE=26.13.1\nlower=1\nUV=0.13.8\n"
    assert dict(pins_of(text)) == {"NODE": "26.13.1", "UV": "0.13.8"}
