import pytest

from tests.helpers import assert_names_the_fix

RESHAPE = (
    "fix: name, type or restructure the code so it needs none,"
    " or, if it explains what we can't reshape, a `comment` exception with"
    " its reason"
)


@pytest.mark.parametrize(
    "message",
    [
        f"comment; {RESHAPE}",
        f"docstring; {RESHAPE}",
        "type comment; fix: use an annotation",
        (
            "triple-slash directive; fix: name it in"
            " `compilerOptions.types` in tsconfig.json"
        ),
        (
            "`# noqa` silences ruff; fix: change the code so ruff passes,"
            " or, if the rule can't apply, an exception in exceptions.toml"
        ),
    ],
)
def test_a_message_naming_the_fix_passes(message: str) -> None:
    assert_names_the_fix(message)


@pytest.mark.parametrize(
    "message",
    [
        "suppression `# noqa`; add an entry to exceptions.toml instead",
        "tool.ruff.preview is off (exception rule `drift:tool.ruff.preview`)",
        "comment; fix: ",
        "; fix: remove it",
        "`#[expect(x)]` is not in exceptions.toml; fix: add it",
        "retries hide failing tests; fix: list each flaky test in exceptions.toml",
    ],
)
def test_a_message_naming_only_the_rule_or_its_escape_fails(
    message: str,
) -> None:
    with pytest.raises(AssertionError):
        assert_names_the_fix(message)
