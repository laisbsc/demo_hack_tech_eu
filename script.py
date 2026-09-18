from typing import Any

import logfire

from pydantic_ai import Agent
from openai.types.chat import ChatCompletion
from pydantic_ai.models.openai import OpenAIChatModel, _ChatCompletion
from pydantic_ai.providers.gateway import gateway_provider

logfire.configure()
logfire.instrument_pydantic_ai()

# Modal returns `metadata.weight_versions` as a list, but the OpenAI schema types
# `metadata` as `dict[str, str]`. Widen it on both models that see the payload:
# the SDK's (which serializes it) and pydantic-ai's (which validates it).
for _model in (ChatCompletion, _ChatCompletion):
    _model.model_fields['metadata'].annotation = dict[str, Any] | None
    _model.model_rebuild(force=True)

provider = gateway_provider('openai-chat', route='modal')
model = OpenAIChatModel('google/gemma-4-31B-it', provider=provider)
agent = Agent(model)

result = agent.run_sync('Explain how HTTPS certificate validation works.')

logfire.span(f'Here is the output in a logfire span: {result.output}')
print(f'Here is the output: {result.output=}')
