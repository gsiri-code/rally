from __future__ import annotations

from types import SimpleNamespace

import rag.rag as rag_module


class _FakeQdrantClient:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        del args, kwargs

    def collection_exists(self, collection_name: str) -> bool:
        del collection_name
        return True

    def query_points(self, *args, **kwargs):  # noqa: ANN002, ANN003
        del args, kwargs
        points = [
            SimpleNamespace(
                id="a",
                score=0.31,
                payload={
                    "name": "A",
                    "summary": "Alpha",
                    "type": "attraction",
                    "destination": "Paris",
                    "link": "https://a.example/item",
                    "source": "rag",
                },
            ),
            SimpleNamespace(
                id="b",
                score=0.89,
                payload={
                    "name": "B",
                    "summary": "Beta",
                    "type": "attraction",
                    "destination": "Paris",
                    "link": "https://b.example/item",
                    "source": "rag",
                },
            ),
        ]
        return SimpleNamespace(points=points)


def _settings(*, rerank_enabled: bool) -> rag_module.RagSettings:
    return rag_module.RagSettings(
        qdrant_url="http://qdrant",
        qdrant_api_key="qdrant-key",
        nvidia_api_key="nvidia-key",
        nvidia_model="nvidia/llama-nemotron-embed-vl-1b-v2",
        rerank_enabled=rerank_enabled,
        rerank_model="nvidia/nv-rerankqa-mistral-4b-v3",
        rerank_url="https://integrate.api.nvidia.com/v1/retranking",
        rerank_top_n=1,
        rerank_timeout_sec=5.0,
        rerank_max_attempts=1,
    )


def test_rag_retrieve_applies_reranking(monkeypatch) -> None:
    monkeypatch.setattr(rag_module, "QdrantClient", _FakeQdrantClient)
    monkeypatch.setattr(rag_module, "_embed_text", lambda text, settings: [0.1, 0.2])
    monkeypatch.setattr(
        rag_module, "_load_settings", lambda: _settings(rerank_enabled=True)
    )

    def fake_rerank(**kwargs):
        candidates = kwargs["candidates"]
        best = dict(candidates[1])
        best["rerank_score"] = 0.98
        best["rank_source"] = "rerank"
        return [best]

    monkeypatch.setattr(rag_module, "rerank_candidates", fake_rerank)

    result = rag_module.rag_retrieve(query_text="best things in paris")

    assert result["rerank_applied"] is True
    assert result["count"] == 1
    assert result["candidates"][0]["id"] == "b"
    assert result["candidates"][0]["rank_source"] == "rerank"


def test_rag_retrieve_skips_reranking_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(rag_module, "QdrantClient", _FakeQdrantClient)
    monkeypatch.setattr(rag_module, "_embed_text", lambda text, settings: [0.1, 0.2])
    monkeypatch.setattr(
        rag_module, "_load_settings", lambda: _settings(rerank_enabled=False)
    )

    result = rag_module.rag_retrieve(query_text="best things in paris")

    assert result["rerank_applied"] is False
    assert result["rerank_model"] is None
    assert result["count"] == 2
    assert {item["rank_source"] for item in result["candidates"]} == {"vector"}


def test_rag_retrieve_falls_back_when_rerank_fails(monkeypatch) -> None:
    monkeypatch.setattr(rag_module, "QdrantClient", _FakeQdrantClient)
    monkeypatch.setattr(rag_module, "_embed_text", lambda text, settings: [0.1, 0.2])
    monkeypatch.setattr(
        rag_module, "_load_settings", lambda: _settings(rerank_enabled=True)
    )

    def failing_rerank(**kwargs):
        del kwargs
        raise RuntimeError("mock rerank failure")

    monkeypatch.setattr(rag_module, "rerank_candidates", failing_rerank)

    result = rag_module.rag_retrieve(query_text="best things in paris")

    assert result["rerank_applied"] is False
    assert result["count"] == 2
    assert "mock rerank failure" in str(result["rerank_error"])
    assert {item["rank_source"] for item in result["candidates"]} == {"vector"}
