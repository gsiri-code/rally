from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class AgentSettings:
    openrouter_api_key: str | None
    openrouter_base_url: str
    nemotron_model: str
    web_search_api_url: str | None
    web_search_api_key: str | None
    rerank_api_url: str | None
    rerank_api_key: str | None
    generate_api_url: str | None
    generate_api_key: str | None
    max_iterations: int
    max_tool_retries: int
    max_recovery_loops: int


def load_settings() -> AgentSettings:
    load_dotenv()
    return AgentSettings(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
        openrouter_base_url=os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        nemotron_model=os.getenv(
            "NEMOTRON_MODEL", "nvidia/llama-3.1-nemotron-nano-8b-v1"
        ),
        web_search_api_url=os.getenv("WEB_SEARCH_API_URL"),
        web_search_api_key=os.getenv("WEB_SEARCH_API_KEY"),
        rerank_api_url=os.getenv("RERANK_API_URL"),
        rerank_api_key=os.getenv("RERANK_API_KEY"),
        generate_api_url=os.getenv("GENERATE_ITINERARY_API_URL"),
        generate_api_key=os.getenv("GENERATE_ITINERARY_API_KEY"),
        max_iterations=int(os.getenv("AGENT_MAX_ITERATIONS", "8")),
        max_tool_retries=int(os.getenv("AGENT_MAX_TOOL_RETRIES", "1")),
        max_recovery_loops=int(os.getenv("AGENT_MAX_RECOVERY_LOOPS", "1")),
    )
