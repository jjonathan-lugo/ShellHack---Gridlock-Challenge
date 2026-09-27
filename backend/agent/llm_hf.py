"""Hugging Face Inference API backend for backend/agent/recommend.py.

Free/low-cost alternative to a paid LLM API for the coordination-
recommendation agent (add-on idea: "maybe use some Hugging Face agents").
Reads HF_TOKEN from the environment and calls a hosted instruction-tuned
model — no local GPU needed.
"""

from __future__ import annotations

import os

# Any instruction-tuned model available on the HF Inference API works here;
# swap for a smaller one if this one isn't warm/available on the free tier.
DEFAULT_MODEL = "meta-llama/Llama-3.1-8B-Instruct"


def make_hf_llm_call(model: str = DEFAULT_MODEL):
    """Returns a call_llm(prompt) -> str function bound to a Hugging Face
    Inference API model, matching the LLMCall signature backend.agent.recommend.recommend() expects.

    Raises RuntimeError with a clear message if HF_TOKEN isn't set, rather
    than failing deep inside a request.
    """
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError(
            "HF_TOKEN is not set. Get a free token at "
            "https://huggingface.co/settings/tokens and set it as an "
            "environment variable (export HF_TOKEN=hf_...) before using the "
            "recommendation agent."
        )

    from huggingface_hub import InferenceClient

    client = InferenceClient(model=model, token=token)

    def call_llm(prompt: str) -> str:
        response = client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
        )
        return response.choices[0].message.content

    return call_llm
