"""Starting an agent session on whichever model a configuration names."""

from collections.abc import Sequence

from otter.agent_session import AgentSession, AgentTool
from otter.auth_resolver import AuthResolver, create_environment_auth_resolver
from otter.chat_completions_agent_session import ChatCompletionsAgentSession
from otter.model import ModelConfig, ModelFactory
from otter.model_factory import create_model_factory

type SystemPrompt = str

_resolve_from_environment = create_environment_auth_resolver()
_create_known_model = create_model_factory()


def create_agent_session(
    system_prompt: SystemPrompt,
    tools: Sequence[AgentTool],
    model_config: ModelConfig,
    *,
    auth_resolver: AuthResolver = _resolve_from_environment,
    model_factory: ModelFactory = _create_known_model,
) -> AgentSession:
    """Start an agent session on the model `model_config` names.

    `system_prompt` is what the model sees ahead of every turn, and `tools` are what it
    may ask to have run.

    `auth_resolver` is asked for the API key of the configuration's provider; leave it
    out to read the key from the environment variable `<PROVIDER>_API_KEY`.
    `model_factory` then makes the model from the configuration and that key; leave it
    out for the models otter reaches out of the box (see `create_model_factory`).
    Whatever either raises propagates: a key that cannot be found, or a configuration no
    model can be made for.
    """
    model = model_factory(model_config, auth_resolver(model_config.provider))
    return ChatCompletionsAgentSession(model, system=system_prompt, tools=tools)
