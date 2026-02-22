from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from planner_agent.errors import PlannerConfigurationError, PlannerGenerationError

NEMOTRON_MODEL_ID = "nvidia/nemotron-3-nano-30b-a3b:free"


@dataclass(frozen=True)
class OpenRouterNemotronClient:
    api_key: str
    base_url: str = "https://openrouter.ai/api/v1"
    timeout_sec: float = 30.0
    max_attempts: int = 3
    backoff_seconds: float = 0.5

    @classmethod
    def from_env(cls) -> OpenRouterNemotronClient | None:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        )

    def generate_outline(self, *, prompt_payload: dict[str, Any]) -> dict[str, Any]:
        system_prompt = (
            "You are a travel planner. Return JSON only, no markdown. "
            "Build a complete itinerary with coherent pacing and realistic flow."
        )
        user_prompt = (
            "Create itinerary JSON with this exact shape: "
            '{"destination": string|null, "days": [{"day_index": int, '
            '"segments": [{"slot": "morning"|"afternoon"|"evening", '
            '"title": string, "description": string, "place_name": string|null, '
            '"citation_urls": [string]}]}], '
            '"assumptions": [string], "budget_notes": [string], '
            '"warnings": [string], "open_questions": [string], '
            '"confidence_reasons": [string]}.\n'
            "Ensure each day has up to 3 segments and only canonical slots.\n"
            f"Input: {json.dumps(prompt_payload, ensure_ascii=True)}"
        )

        payload = {
            "model": NEMOTRON_MODEL_ID,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "top_p": 1,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with httpx.Client(timeout=self.timeout_sec) as client:
                    response = client.post(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                response.raise_for_status()
                body = response.json()
                return _extract_outline_json(body)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt == self.max_attempts:
                    break
                time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))

        raise PlannerGenerationError(
            f"Nemotron generation failed after retries: {last_error}"
        )


def _extract_outline_json(response_body: dict[str, Any]) -> dict[str, Any]:
    choices = response_body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise PlannerGenerationError("OpenRouter response did not include choices.")

    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    text = _content_to_text(content)
    if not text:
        raise PlannerGenerationError("OpenRouter returned empty content.")

    parsed = _parse_json_text(text)
    if not isinstance(parsed, dict):
        raise PlannerGenerationError("Model output is not a JSON object.")
    return parsed


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text")
                if isinstance(value, str):
                    parts.append(value)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts).strip()
    return ""


def _parse_json_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced_match = re.search(r"```json\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced_match:
        return json.loads(fenced_match.group(1))

    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        return json.loads(text[first : last + 1])

    raise PlannerGenerationError("Unable to parse JSON from model output.")


def assert_hardcoded_model_guard() -> None:
    configured = os.getenv("OPENROUTER_MODEL")
    if configured and configured != NEMOTRON_MODEL_ID:
        raise PlannerConfigurationError(
            "OPENROUTER_MODEL override is not allowed; planner is hardcoded to "
            f"{NEMOTRON_MODEL_ID}."
        )
