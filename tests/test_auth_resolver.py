"""Behaviour of the environment auth resolver, observed against a fake environment."""

import pytest

from otter.auth_resolver import MissingApiKeyError, create_environment_auth_resolver


@pytest.mark.parametrize(
    "provider, variable",
    [
        ("zai", "ZAI_API_KEY"),
        ("OpenAI", "OPENAI_API_KEY"),
        ("open-router", "OPEN_ROUTER_API_KEY"),
    ],
)
def test_a_providers_key_is_read_from_its_api_key_variable(provider: str, variable: str) -> None:
    resolve = create_environment_auth_resolver({variable: "secret-key", "OTHER_API_KEY": "no"})

    assert resolve(provider) == "secret-key"


@pytest.mark.parametrize("environ", [{}, {"ZAI_API_KEY": ""}])
def test_a_provider_with_no_key_set_raises_naming_the_variable(environ: dict[str, str]) -> None:
    resolve = create_environment_auth_resolver(environ)

    with pytest.raises(
        MissingApiKeyError, match=r"^no API key for provider 'zai': set ZAI_API_KEY$"
    ):
        resolve("zai")


def test_a_key_set_after_the_resolver_was_created_is_found() -> None:
    environ: dict[str, str] = {}
    resolve = create_environment_auth_resolver(environ)

    environ["ZAI_API_KEY"] = "late-key"

    assert resolve("zai") == "late-key"
