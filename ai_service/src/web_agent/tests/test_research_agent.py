from __future__ import annotations

import json
from types import SimpleNamespace

from orchestrator_agent.contracts import ImageHint

from web_agent.research import (
    EVIDENCE_SYSTEM_PROMPT,
    ClaudeResearchAgent,
    ClaudeResearchConfig,
)


class _FakeMessages:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = responses
        self._index = 0
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self._responses[self._index]
        self._index += 1
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])


class _FakeClient:
    def __init__(self, responses: list[dict]) -> None:
        self.messages = _FakeMessages(responses)


def _agent_for(responses: list[dict]) -> ClaudeResearchAgent:
    return ClaudeResearchAgent(
        config=ClaudeResearchConfig(api_key="test-key"),
        client=_FakeClient(responses),
        sleeper=lambda _: None,
    )


def test_default_web_search_tool_is_20250305() -> None:
    payload = {"evidence": [], "citations": []}
    client = _FakeClient([payload])
    agent = ClaudeResearchAgent(
        config=ClaudeResearchConfig(api_key="test-key"),
        client=client,
        sleeper=lambda _: None,
    )

    _ = agent.gather_evidence(query_text="Paris", destination="Paris", constraints={})
    assert client.messages.calls
    assert client.messages.calls[0]["tools"][0]["type"] == "web_search_20250305"
    assert client.messages.calls[0]["system"] == EVIDENCE_SYSTEM_PROMPT


def test_gather_evidence_dedupes_urls_and_returns_contract_models() -> None:
    payload = {
        "evidence": [
            {
                "name": "Louvre Museum",
                "summary": "Major museum in Paris.",
                "link": "https://www.louvre.fr/en?utm_source=test",
                "source": "louvre.fr",
                "ingested_at": "2026-01-10T00:00:00Z",
                "confidence": 0.9,
            },
            {
                "name": "Louvre Duplicate",
                "summary": "Duplicate URL variant.",
                "link": "https://louvre.fr/en",
                "source": "louvre.fr",
                "confidence": 0.7,
            },
        ],
        "citations": [],
    }
    agent = _agent_for([payload])

    result = agent.gather_evidence(
        query_text="Top Paris museums",
        destination="Paris",
        constraints={},
    )

    assert len(result.evidence) == 1
    assert result.evidence[0].link == "https://louvre.fr/en"
    assert len(result.citations) == 1
    assert result.citations[0].url == "https://louvre.fr/en"


def test_gather_images_prefers_non_reused_images_with_fallback() -> None:
    segment_a = {
        "images": [
            {
                "url": "https://images.example.com/a.jpg?w=1000",
                "thumbnail_url": None,
                "alt": "A",
                "source": "example.com",
                "attribution": None,
                "license": None,
                "width": 1000,
                "height": 1000,
                "confidence": 0.9,
            }
        ]
    }
    segment_b = {
        "images": [
            {
                "url": "https://images.example.com/a.jpg?w=400",
                "thumbnail_url": None,
                "alt": "A duplicate",
                "source": "example.com",
                "attribution": None,
                "license": None,
                "width": 400,
                "height": 400,
                "confidence": 0.95,
            },
            {
                "url": "https://images.example.com/b.jpg",
                "thumbnail_url": None,
                "alt": "B",
                "source": "example.com",
                "attribution": None,
                "license": None,
                "width": 1200,
                "height": 900,
                "confidence": 0.7,
            },
        ]
    }

    agent = _agent_for([segment_a, segment_b])
    result = agent.gather_images(
        image_hints_by_segment={
            "s1": ImageHint(query="Eiffel Tower"),
            "s2": ImageHint(query="Paris cafe"),
        },
        destination="Paris",
    )

    assert (
        result.images_by_segment["s1"][0].url
        == "https://images.example.com/a.jpg?w=1000"
    )
    assert result.images_by_segment["s2"][0].url == "https://images.example.com/b.jpg"
