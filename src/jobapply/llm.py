import os

from openai import OpenAI

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


class LLM:
    """Thin provider-agnostic wrapper (TECH_REQUIREMENT.md: LLM Provider).

    Backed by Groq's OpenAI-compatible endpoint for now. Swapping to Claude
    or another provider later only requires changing this class, not the
    agents that call it.
    """

    def __init__(self, model: str = DEFAULT_MODEL):
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable is not set")
        self._client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)
        self._model = model

    def complete(self, prompt: str, *, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content or ""
