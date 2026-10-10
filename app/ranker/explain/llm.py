"""Claude client wrapper. Returns None when no key is configured so the app still works."""
from typing import Callable, Optional

from ..config import Settings


def make_llm_call(settings: Settings) -> Optional[Callable[[str, str], str]]:
    use_llm = settings.explain_mode != "template" and bool(settings.anthropic_api_key)
    if not use_llm:
        return None

    import anthropic  # imported here so template mode needs no network client

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def call(system: str, prompt: str) -> str:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    return call
