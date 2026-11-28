from checks.core.sides import side_of
from checks.core.tools import run
from tests.helpers import inputs, lines


def test_files_under_tests_named_test_or_conftest_are_tests() -> None:
    for path in (
        "tests/helpers.py",
        "pkg/tests/data/x.py",
        "pkg/test_core.py",
        "python/conftest.py",
    ):
        assert side_of(path) == "tests", path


def test_files_under_a_test_folder_are_tests_in_either_language() -> None:
    for path in (
        "pkg/test/x.py",
        "src/__tests__/a.ts",
        "test/oxlint.ts",
        "src/a.spec.ts",
        "src/a.test.tsx",
    ):
        assert side_of(path) == "tests", path


def test_every_other_typescript_file_is_a_source() -> None:
    for path in ("src/testing.ts", "src/contest.ts", "src/index.mjs"):
        assert side_of(path) == "sources", path


def test_every_other_python_file_is_a_source() -> None:
    for path in ("pkg/core.py", "pkg/testing.py", "pkg/core_test_utils.py"):
        assert side_of(path) == "sources", path
    assert side_of("app/main.pyw") == "sources"


def test_a_file_that_is_not_python_has_no_side() -> None:
    for path in (
        "tests/data.json",
        "pyproject.toml",
        "pkg/test_core.rs",
        "src/a.spec.css",
    ):
        assert side_of(path) is None, path


def test_sides_names_the_side_of_each_python_file_it_reads() -> None:
    listed = "pkg/core.py\ntests/test_core.py\nREADME.md\n"
    assert lines(run(("sides",), inputs({}, listed))) == (
        "sources\tpkg/core.py",
        "tests\ttests/test_core.py",
    )
