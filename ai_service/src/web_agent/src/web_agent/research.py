from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypeVar
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from anthropic import Anthropic
from pydantic import BaseModel, Field

from orchestrator_agent.contracts import (
    Citation,
    ImageAsset,
    ImageHint,
    ResearchEvidence,
    ResearchEvidenceResult,
    ResearchImagesResult,
)

_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_DEFAULT_WEB_SEARCH_TOOL = "web_search_20250305"
_DEFAULT_TIMEOUT_SEC = 45.0
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BACKOFF_BASE_SEC = 0.75
_MAX_IMAGES_PER_SEGMENT = 3

EVIDENCE_SYSTEM_PROMPT = (
    "You are Rally Research, a travel intelligence analyst. "
    "Use web search to collect factual, high-signal evidence for itinerary planning. "
    "Prioritize primary and reputable sources, avoid low-trust aggregators when better sources exist, "
    "and prefer current information. "
    "Return strict JSON only with no markdown or extra prose."
)

IMAGES_SYSTEM_PROMPT = (
    "You are Rally Imagery, a travel visual curator. "
    "Use web search to find real, attributable travel images that match each itinerary segment. "
    "Prioritize trustworthy hosts, relevance, and usable metadata. "
    "Return strict JSON only with no markdown or extra prose."
)

_TRACKING_QUERY_PARAMS = {
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "spm",
    "source",
}

_IMAGE_VARIANT_QUERY_PARAMS = {
    "auto",
    "crop",
    "fit",
    "fm",
    "format",
    "h",
    "height",
    "q",
    "quality",
    "w",
    "width",
}

TModel = TypeVar("TModel", bound=BaseModel)


@dataclass(frozen=True)
class ClaudeResearchConfig:
    api_key: str
    model: str = _DEFAULT_MODEL
    web_search_tool: str = _DEFAULT_WEB_SEARCH_TOOL
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC
    max_retries: int = _DEFAULT_MAX_RETRIES
    backoff_base_sec: float = _DEFAULT_BACKOFF_BASE_SEC

    @classmethod
    def from_env(cls) -> "ClaudeResearchConfig":
        api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError(
                "Missing required environment variable ANTHROPIC_API_KEY."
            )

        model = (os.getenv("CLAUDE_MODEL") or _DEFAULT_MODEL).strip()
        web_search_tool = (
            os.getenv("CLAUDE_WEB_SEARCH_TOOL") or _DEFAULT_WEB_SEARCH_TOOL
        ).strip()

        timeout_sec = _read_float_env("RESEARCH_TIMEOUT_SEC", _DEFAULT_TIMEOUT_SEC)
        max_retries = _read_int_env("RESEARCH_MAX_RETRIES", _DEFAULT_MAX_RETRIES)
        backoff_base_sec = _read_float_env(
            "RESEARCH_BACKOFF_BASE_SEC", _DEFAULT_BACKOFF_BASE_SEC
        )

        return cls(
            api_key=api_key,
            model=model,
            web_search_tool=web_search_tool,
            timeout_sec=timeout_sec,
            max_retries=max(1, max_retries),
            backoff_base_sec=max(0.05, backoff_base_sec),
        )


class _ClaudeCitation(BaseModel):
    url: str
    source: str
    title: str | None = None


class _ClaudeEvidenceItem(BaseModel):
    name: str
    summary: str
    link: str
    source: str
    ingested_at: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class _ClaudeEvidencePayload(BaseModel):
    evidence: list[_ClaudeEvidenceItem] = Field(default_factory=list)
    citations: list[_ClaudeCitation] = Field(default_factory=list)


class _ClaudeImageCandidate(BaseModel):
    url: str
    thumbnail_url: str | None = None
    alt: str
    source: str
    attribution: str | None = None
    license: str | None = None
    width: int | None = None
    height: int | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class _ClaudeImagePayload(BaseModel):
    images: list[_ClaudeImageCandidate] = Field(default_factory=list)


class ClaudeResearchAgent:
    def __init__(
        self,
        *,
        config: ClaudeResearchConfig | None = None,
        client: Anthropic | None = None,
        sleeper=time.sleep,
    ) -> None:
        self.config = config or ClaudeResearchConfig.from_env()
        self.client = client or Anthropic(
            api_key=self.config.api_key,
            timeout=self.config.timeout_sec,
            max_retries=0,
        )
        self._sleep = sleeper

    def gather_evidence(
        self,
        *,
        query_text: str,
        destination: str | None,
        constraints: dict,
    ) -> ResearchEvidenceResult:
        prompt = self._build_evidence_prompt(
            query_text=query_text,
            destination=destination,
            constraints=constraints,
        )

        try:
            payload = self._call_json_with_retry(
                prompt=prompt,
                parser=_ClaudeEvidencePayload,
                system_prompt=EVIDENCE_SYSTEM_PROMPT,
            )
        except Exception:
            return ResearchEvidenceResult(
                evidence=[], citations=[], freshness_ratio=None
            )

        evidence_by_url: dict[str, ResearchEvidence] = {}
        citations_by_url: dict[str, Citation] = {}

        for item in payload.evidence:
            canonical = _canonicalize_url(item.link)
            if not canonical:
                continue
            if canonical in evidence_by_url:
                continue
            evidence_by_url[canonical] = ResearchEvidence(
                evidence_id=_stable_id("ev", canonical),
                name=item.name.strip(),
                summary=item.summary.strip(),
                link=canonical,
                source=item.source.strip(),
                ingested_at=_normalize_datetime(item.ingested_at),
                confidence=_clamp_confidence(item.confidence),
            )

        for item in payload.citations:
            canonical = _canonicalize_url(item.url)
            if not canonical:
                continue
            if canonical in citations_by_url:
                continue
            citations_by_url[canonical] = Citation(
                id=_stable_id("cit", canonical),
                url=canonical,
                source=item.source.strip(),
                title=(item.title or None),
            )

        for evidence in evidence_by_url.values():
            link = _canonicalize_url(evidence.link)
            if link and link not in citations_by_url:
                citations_by_url[link] = Citation(
                    id=_stable_id("cit", link),
                    url=link,
                    source=evidence.source,
                    title=evidence.name,
                )

        return ResearchEvidenceResult(
            evidence=list(evidence_by_url.values()),
            citations=list(citations_by_url.values()),
            freshness_ratio=None,
        )

    def gather_images(
        self,
        *,
        image_hints_by_segment: dict[str, ImageHint],
        destination: str | None,
    ) -> ResearchImagesResult:
        images_by_segment: dict[str, list[ImageAsset]] = {}
        used_image_keys: set[str] = set()

        for segment_id, hint in image_hints_by_segment.items():
            prompt = self._build_images_prompt(
                segment_id=segment_id,
                hint=hint,
                destination=destination,
            )
            try:
                payload = self._call_json_with_retry(
                    prompt=prompt,
                    parser=_ClaudeImagePayload,
                    system_prompt=IMAGES_SYSTEM_PROMPT,
                )
            except Exception:
                images_by_segment[segment_id] = []
                continue

            candidates = self._dedupe_image_candidates(payload.images)
            if not candidates:
                images_by_segment[segment_id] = []
                continue

            preferred = [
                image
                for image in candidates
                if _image_key(image.url) not in used_image_keys
            ]
            chosen_pool = preferred or candidates

            selected: list[ImageAsset] = []
            for item in chosen_pool[:_MAX_IMAGES_PER_SEGMENT]:
                canonical = _canonicalize_url(item.url)
                if not canonical:
                    continue
                img = ImageAsset(
                    id=_stable_id("img", f"{segment_id}:{canonical}"),
                    url=canonical,
                    thumbnail_url=_canonicalize_url(item.thumbnail_url),
                    alt=item.alt.strip() if item.alt.strip() else hint.query,
                    source=item.source.strip(),
                    attribution=item.attribution,
                    license=item.license,
                    width=item.width,
                    height=item.height,
                    confidence=_clamp_confidence(item.confidence),
                )
                selected.append(img)
                used_image_keys.add(_image_key(canonical))

            images_by_segment[segment_id] = selected

        return ResearchImagesResult(images_by_segment=images_by_segment)

    def _call_json_with_retry(
        self,
        *,
        prompt: str,
        parser: type[TModel],
        system_prompt: str,
    ) -> TModel:
        last_exc: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = self.client.messages.create(
                    model=self.config.model,
                    max_tokens=2400,
                    temperature=0,
                    system=system_prompt,
                    tools=[
                        {
                            "type": self.config.web_search_tool,
                            "name": "web_search",
                        }
                    ],
                    messages=[{"role": "user", "content": prompt}],
                )
                text = _extract_text(response)
                payload_obj = _parse_json_object(text)
                return parser.model_validate(payload_obj)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= self.config.max_retries:
                    break
                delay = self.config.backoff_base_sec * (2 ** (attempt - 1))
                delay += random.uniform(0.0, self.config.backoff_base_sec / 2.0)
                self._sleep(delay)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Claude call failed without exception.")

    def _dedupe_image_candidates(
        self, candidates: list[_ClaudeImageCandidate]
    ) -> list[_ClaudeImageCandidate]:
        uniq: dict[str, _ClaudeImageCandidate] = {}
        for item in candidates:
            canonical = _canonicalize_url(item.url)
            if not canonical:
                continue
            key = _image_key(canonical)
            if key in uniq:
                continue
            uniq[key] = item

        ordered = list(uniq.values())
        ordered.sort(key=_image_sort_key)
        return ordered

    def _build_evidence_prompt(
        self,
        *,
        query_text: str,
        destination: str | None,
        constraints: dict,
    ) -> str:
        destination_text = destination or "unknown destination"
        constraints_json = json.dumps(
            constraints or {}, ensure_ascii=True, sort_keys=True
        )
        return (
            "You are a travel research analyst. Use web search to gather evidence for itinerary planning. "
            "Prefer high-signal travel sources: official tourism boards, museums, cultural institutions, "
            "national park/transport operator sites, reputable travel publications, and major booking or map providers. "
            "Find at least 5 distinct evidence items when available. "
            "Return ONLY valid JSON with this schema: "
            '{"evidence":[{"name":str,"summary":str,"link":str,"source":str,"ingested_at":str|null,"confidence":number|null}],'
            '"citations":[{"url":str,"source":str,"title":str|null}]}. '
            "No markdown, no prose. "
            f"Destination: {destination_text}. "
            f"User request: {query_text}. "
            f"Constraints: {constraints_json}."
        )

    def _build_images_prompt(
        self,
        *,
        segment_id: str,
        hint: ImageHint,
        destination: str | None,
    ) -> str:
        destination_text = destination or "unknown destination"
        must_match = "yes" if hint.must_match_landmark else "no"
        place_name = hint.place_name or ""
        return (
            "You are selecting travel imagery for itinerary segments. Use web search to find real image URLs. "
            "Prefer trustworthy sources and images that can be attributed. "
            "Prefer near-square imagery (aspect ratio close to 1:1) when dimensions are known; "
            "if unavailable, gracefully fall back to best non-square options. "
            "Return ONLY valid JSON with this schema: "
            '{"images":[{"url":str,"thumbnail_url":str|null,"alt":str,"source":str,'
            '"attribution":str|null,"license":str|null,"width":int|null,"height":int|null,"confidence":number|null}]}. '
            "Provide 1 to 3 images if available. No markdown, no prose. "
            f"Destination: {destination_text}. "
            f"Segment ID: {segment_id}. "
            f"Hint query: {hint.query}. "
            f"Place name: {place_name}. "
            f"Must match landmark: {must_match}."
        )


_DEFAULT_AGENT: ClaudeResearchAgent | None = None


def get_research_agent() -> ClaudeResearchAgent:
    global _DEFAULT_AGENT
    if _DEFAULT_AGENT is None:
        _DEFAULT_AGENT = ClaudeResearchAgent()
    return _DEFAULT_AGENT


def gather_evidence(
    *, query_text: str, destination: str | None, constraints: dict
) -> ResearchEvidenceResult:
    return get_research_agent().gather_evidence(
        query_text=query_text,
        destination=destination,
        constraints=constraints,
    )


def gather_images(
    *, image_hints_by_segment: dict[str, ImageHint], destination: str | None
) -> ResearchImagesResult:
    return get_research_agent().gather_images(
        image_hints_by_segment=image_hints_by_segment,
        destination=destination,
    )


def _read_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _read_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _extract_text(response: Any) -> str:
    chunks: list[str] = []
    for block in getattr(response, "content", []):
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            chunks.append(text)
    return "\n".join(chunks).strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    if not text:
        raise RuntimeError("Claude response was empty.")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < 0 or end <= start:
            raise RuntimeError("Claude response did not contain JSON.")
        parsed = json.loads(text[start : end + 1])

    if not isinstance(parsed, dict):
        raise RuntimeError("Claude JSON payload must be an object.")
    return parsed


def _canonicalize_url(url: str | None) -> str:
    if not url:
        return ""

    candidate = url.strip()
    if not candidate:
        return ""

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if not parsed.netloc:
        return ""

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key_lower = key.lower()
        if key_lower.startswith("utm_"):
            continue
        if key_lower in _TRACKING_QUERY_PARAMS:
            continue
        query_items.append((key, value))

    query_items.sort(key=lambda item: item[0])
    clean_query = urlencode(query_items, doseq=True)
    clean_path = parsed.path or "/"

    return urlunparse(("https", host, clean_path, "", clean_query, ""))


def _image_key(url: str) -> str:
    canonical = _canonicalize_url(url)
    if not canonical:
        return ""
    parsed = urlparse(canonical)
    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower() in _IMAGE_VARIANT_QUERY_PARAMS:
            continue
        query_items.append((key, value))
    query_items.sort(key=lambda item: item[0])
    clean_query = urlencode(query_items, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", clean_query, ""))


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{prefix}_{digest[:12]}"


def _normalize_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _clamp_confidence(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _image_sort_key(item: _ClaudeImageCandidate) -> tuple[float, float]:
    confidence = item.confidence if item.confidence is not None else 0.0
    square_score = 0.0
    if item.width and item.height and item.width > 0 and item.height > 0:
        ratio = item.width / item.height
        square_score = abs(1.0 - ratio)
    else:
        square_score = 10.0

    return (square_score, -confidence)
