"""A conversation with a model served over an OpenAI-compatible responses endpoint."""

import json
from collections.abc import Sequence
from typing import assert_never, cast

from openai import AsyncOpenAI, omit
from openai.types.responses import (
    FunctionToolParam,
    ResponseInputContentParam,
    ResponseInputItemParam,
)

from otter.messages import (
    AssistantMessage,
    AssistantPart,
    AudioPart,
    ContextEntry,
    ImagePart,
    ImageUrlPart,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolResultMessage,
    ToolSpec,
    UserMessage,
    UserPart,
)


class OpenAIResponsesCompatibleConversation:
    """One conversation with one model: it holds the history and generates the next turn.

    The client decides which provider is spoken to (its base URL and API key); any
    provider serving the responses format will do. `system` is the system prompt the
    model sees ahead of every turn, and `tools` are the tools it may ask to have called.
    `context` is the history the conversation starts out with, oldest first; the
    thinking in its assistant turns is not sent.

    The whole history is sent with each request and the provider is asked to keep none
    of it, so the conversation lives only here.

    `supports_images` says whether the model can take images in. Where it is false, an
    image is not sent: a short text note saying it was omitted goes to the model in its
    place, so the conversation stays usable. The responses format has no place for
    audio, so audio is always replaced by such a note.

    A refusal is returned as the text of the model's turn. Reasoning is returned as
    thinking where the provider shows it, and not at all where it does not.

    An instance is a single conversation, so concurrent calls to `generate` on one
    instance are not supported.
    """

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        *,
        system: str | None = None,
        tools: Sequence[ToolSpec] = (),
        context: Sequence[ContextEntry] = (),
        supports_images: bool = True,
    ) -> None:
        self._client = client
        self._model = model
        self._system = system
        self._supports_images = supports_images
        # Kept in wire form: the history is only ever read back by the endpoint.
        self._items: list[ResponseInputItemParam] = []
        self._tools: list[FunctionToolParam] = [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
                # Left out, the endpoint holds the schema to its strict rules, which a
                # tool's schema need not meet.
                "strict": False,
            }
            for tool in tools
        ]
        for entry in context:
            match entry:
                case UserMessage():
                    self.add_user_message(entry.content)
                case AssistantMessage():
                    self._items.extend(_assistant_turn_on_the_wire(entry))
                case ToolResultMessage():
                    self.add_tool_result(entry.tool_call_id, entry.text)
                case _:
                    assert_never(entry)

    def add_user_message(self, content: Sequence[UserPart]) -> None:
        """Append a user turn; it is sent to the model on the next `generate`."""
        self._items.append({"role": "user", "content": [self._on_the_wire(p) for p in content]})

    def _on_the_wire(self, part: UserPart) -> ResponseInputContentParam:
        match part:
            case TextPart():
                return {"type": "input_text", "text": part.text}
            case ImagePart() | ImageUrlPart() if not self._supports_images:
                return {
                    "type": "input_text",
                    "text": "[image omitted: this model cannot view images]",
                }
            case ImagePart():
                return {
                    "type": "input_image",
                    "image_url": f"data:{part.media_type};base64,{part.data}",
                    "detail": "auto",
                }
            case ImageUrlPart():
                return {"type": "input_image", "image_url": part.url, "detail": "auto"}
            case AudioPart():
                return {
                    "type": "input_text",
                    "text": "[audio omitted: this model cannot hear audio]",
                }
            case _:
                assert_never(part)

    async def generate(self) -> AssistantMessage:
        """Send the conversation so far to the model and return the turn it produces.

        The returned turn joins the history. The conversation is sent as it stands: one
        the provider cannot accept, such as a tool call left without a result, is the
        provider's to reject. If the request fails, the provider reports that the model
        failed (a `RuntimeError`), or the model's turn cannot be read (tool arguments
        that are not valid JSON raise `json.JSONDecodeError`), the error propagates and
        the history is left as it was.
        """
        response = await self._client.responses.create(
            model=self._model,
            input=self._items,
            instructions=self._system if self._system is not None else omit,
            tools=self._tools or omit,
            store=False,
            # With nothing kept by the provider, reasoning can only be sent back in
            # this form.
            include=["reasoning.encrypted_content"],
        )
        if response.error is not None:
            raise RuntimeError(f"the model failed: {response.error.message}")

        # Everything that can fail happens before the history is touched, so a turn that
        # cannot be read leaves the conversation as it was.
        content: list[AssistantPart] = []
        for item in response.output:
            if item.type == "reasoning":
                # Providers differ in where they show reasoning: OpenAI as a summary,
                # Z.ai as the reasoning itself.
                shown = item.content or item.summary
                thinking = "\n\n".join(part.text for part in shown)
                if thinking:
                    content.append(ThinkingPart(thinking))
            elif item.type == "message":
                content.extend(
                    TextPart(part.text if part.type == "output_text" else part.refusal)
                    for part in item.content
                )
            elif item.type == "function_call":
                content.append(
                    ToolCall(id=item.call_id, name=item.name, arguments=json.loads(item.arguments))
                )

        # The model's items go back exactly as it produced them, reasoning included.
        self._items.extend(
            cast(ResponseInputItemParam, item.model_dump(mode="json", exclude_unset=True))
            for item in response.output
        )
        return AssistantMessage(content=tuple(content))

    def add_tool_result(self, tool_call_id: str, text: str) -> None:
        """Append the result of a tool call the model asked for in its last turn."""
        self._items.append(
            {"type": "function_call_output", "call_id": tool_call_id, "output": text}
        )


def _assistant_turn_on_the_wire(message: AssistantMessage) -> list[ResponseInputItemParam]:
    items: list[ResponseInputItemParam] = []
    for part in message.content:
        match part:
            case TextPart():
                items.append({"role": "assistant", "content": part.text})
            case ToolCall():
                items.append(
                    {
                        "type": "function_call",
                        "call_id": part.id,
                        "name": part.name,
                        "arguments": json.dumps(part.arguments),
                    }
                )
            case ThinkingPart():
                # Only the provider's own reasoning items can be sent back, and a
                # context entry does not carry them.
                pass
            case _:
                assert_never(part)
    return items
