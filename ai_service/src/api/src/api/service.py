from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol
from uuid import uuid4

import httpx

from orchestrator_agent.contracts import PlanRequest, PlanResponse

from api.errors import (
    DomainError,
    NotFoundDomainError,
    PayloadTooLargeDomainError,
    RepositoryDomainError,
    UpstreamDomainError,
    ValidationDomainError,
)
from api.mapping import (
    build_trip_id,
    map_compose_input_to_plan_request,
    map_itinerary_to_trip_plan,
    map_trip_create_input_to_plan_request,
)
from api.models import (
    AttractionsSearchInput,
    AttractionsSearchResponse,
    CacheInfo,
    ChangeBlockInput,
    ChangeEvent,
    ComposeInput,
    FlightSearchCreateInput,
    FlightSearchResponse,
    HealthzResponse,
    ItineraryBlock,
    SearchRefs,
    SearchResponse,
    TripCreateInput,
    TripPlan,
    VoiceDecideInput,
    VoiceDecideResponse,
    VoiceDecision,
    VoiceIntentResponse,
    VoiceTranscribeResponse,
)
from api.repository import SearchRepository, TripRecord, TripRepository


class OrchestratorRunner(Protocol):
    def run(self, request: PlanRequest) -> PlanResponse: ...


@dataclass
class TripPlanningService:
    repository: TripRepository
    search_repository: SearchRepository
    orchestrator: OrchestratorRunner

    def healthz(self) -> HealthzResponse:
        databricks_ok = self._check_databricks()
        qdrant_ok = self._check_qdrant()
        anthropic_ok = self._check_anthropic()
        openrouter_ok = self._check_openrouter()
        db_ok = databricks_ok and qdrant_ok
        return HealthzResponse(ok=db_ok and anthropic_ok and openrouter_ok, db=db_ok)

    def create_flight_search(
        self, payload: FlightSearchCreateInput
    ) -> FlightSearchResponse:
        query = {
            "origins": payload.origins,
            "destinations": payload.destinations,
            "depart_date": payload.depart_date,
            "return_date": payload.return_date,
            "adults": payload.adults,
            "cabin": payload.cabin,
            "nonstop_preferred": payload.nonstop_preferred,
            "max_stops": payload.max_stops,
            "currency": payload.currency,
            "limit": payload.limit,
            "trip_id": payload.trip_id,
        }
        try:
            evidence = self._search_with_web_agent(
                query_text=(
                    f"Flights from {', '.join(payload.origins)} to "
                    f"{', '.join(payload.destinations)} on {payload.depart_date}"
                ),
                destination=payload.destinations[0] if payload.destinations else None,
                constraints=query,
            )
        except Exception as exc:  # noqa: BLE001
            raise UpstreamDomainError("Upstream search failed") from exc

        now = datetime.now(timezone.utc)
        response = FlightSearchResponse(
            search_id=f"fls_{uuid4().hex[:12]}",
            query=query,
            status="completed",
            results=evidence,
            notes=[],
            error=None,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=6)).isoformat(),
        )
        self.search_repository.save_search(response, search_type="flight")
        return response

    def get_search(self, search_id: str) -> SearchResponse:
        search = self.search_repository.get_search(search_id)
        if search is None:
            raise NotFoundDomainError(f"Search '{search_id}' was not found.")
        return search

    def create_attractions_search(
        self,
        payload: AttractionsSearchInput,
    ) -> tuple[AttractionsSearchResponse, int]:
        query = payload.model_dump()
        try:
            evidence = self._search_with_web_agent(
                query_text=(
                    f"Top {', '.join(payload.categories)} in {payload.city} on {payload.date}"
                ),
                destination=payload.city,
                constraints=query,
            )
        except Exception as exc:  # noqa: BLE001
            raise UpstreamDomainError("Upstream search failed") from exc

        now = datetime.now(timezone.utc)
        running = len(evidence) == 0
        response = AttractionsSearchResponse(
            search_id=f"ats_{uuid4().hex[:12]}",
            type="attractions",
            query=query,
            status="running" if running else "completed",
            results=evidence,
            notes=["search_in_progress"] if running else [],
            error=None,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=6)).isoformat(),
            cache=CacheInfo(hit=False, key=f"attr:{payload.city}:{payload.date}"),
        )
        as_search = SearchResponse(
            search_id=response.search_id,
            query=response.query,
            status=response.status,
            results=response.results,
            notes=response.notes,
            error=response.error,
            created_at=response.created_at,
            expires_at=response.expires_at,
        )
        self.search_repository.save_search(as_search, search_type="attractions")
        return response, (202 if running else 200)

    def create_trip(self, *, payload: TripCreateInput, use_cache: bool) -> TripPlan:
        trip_id = build_trip_id(payload)
        if use_cache:
            cached = self._get_trip_record_optional(trip_id)
            if cached is not None:
                return cached.trip

        plan_request = map_trip_create_input_to_plan_request(
            payload, request_id=f"req_create_{trip_id}"
        )
        return self._compose_and_persist(
            trip_id=trip_id,
            plan_request=plan_request,
            inputs=payload,
            timezone="UTC",
            flight_search_id=f"flight_{trip_id}",
            attractions_search_id=f"attr_{trip_id}",
        )

    def compose_itinerary(self, *, payload: ComposeInput, use_cache: bool) -> TripPlan:
        record = self._get_trip_record_required(payload.trip_id)
        if use_cache:
            return record.trip

        plan_request = map_compose_input_to_plan_request(
            payload,
            request_id=f"req_compose_{payload.trip_id}",
            base_inputs=record.trip.inputs,
        )
        return self._compose_and_persist(
            trip_id=payload.trip_id,
            plan_request=plan_request,
            inputs=record.trip.inputs,
            timezone=payload.timezone,
            flight_search_id=payload.flight_search_id,
            attractions_search_id=payload.attractions_search_id,
            existing_audit=record.trip.audit_log,
            existing_transit=record.trip.transit,
        )

    def get_trip(self, trip_id: str) -> TripPlan:
        return self._get_trip_record_required(trip_id).trip

    def skip_block(self, trip_id: str, block_id: str) -> TripPlan:
        record = self._get_trip_record_required(trip_id)
        trip = record.trip.model_copy(deep=True)
        block = self._find_block(trip, block_id)
        if block is None:
            raise NotFoundDomainError(f"Block '{block_id}' was not found.")
        block.status = "skipped"
        trip.audit_log.append(
            ChangeEvent(
                ts=datetime.now(timezone.utc).isoformat(),
                action="skip",
                block_id=block_id,
                old_kind=block.kind,
                old_title=block.title,
                old_start_at=block.start_at,
                old_end_at=block.end_at,
                event="block_skipped",
            )
        )
        self._save_trip_record(record, trip)
        return trip

    def change_block(
        self, trip_id: str, block_id: str, payload: ChangeBlockInput
    ) -> TripPlan:
        record = self._get_trip_record_required(trip_id)
        trip = record.trip.model_copy(deep=True)
        block = self._find_block(trip, block_id)
        if block is None:
            raise NotFoundDomainError(f"Block '{block_id}' was not found.")
        old_title = block.title
        old_kind = block.kind
        suffix = payload.direction or "updated"
        block.title = f"{block.title} ({suffix})"
        block.status = "replaced"
        trip.audit_log.append(
            ChangeEvent(
                ts=datetime.now(timezone.utc).isoformat(),
                action="change",
                block_id=block_id,
                reason=payload.preference_text or "manual change",
                direction=payload.direction,
                old_kind=old_kind,
                old_title=old_title,
                old_start_at=block.start_at,
                old_end_at=block.end_at,
                event="block_replaced",
            )
        )
        self._save_trip_record(record, trip)
        return trip

    def transcribe_audio(self, filename: str, data: bytes) -> VoiceTranscribeResponse:
        if len(data) > 15 * 1024 * 1024:
            raise PayloadTooLargeDomainError("Audio too large or long.")
        with NamedTemporaryFile(
            suffix=Path(filename).suffix or ".mp3", delete=True
        ) as tmp:
            tmp.write(data)
            tmp.flush()
            try:
                from transcription import transcribe_mp3

                result = transcribe_mp3(
                    mp3_path=tmp.name,
                    request_id=f"voice_{uuid4().hex[:10]}",
                )
            except Exception as exc:  # noqa: BLE001
                raise UpstreamDomainError("Transcription failed") from exc
        return VoiceTranscribeResponse(transcript=str(result["text"]), error=None)

    def decide_voice(self, payload: VoiceDecideInput) -> VoiceDecideResponse:
        trip = self.get_trip(payload.trip_id)
        decision = self._decide_with_openrouter(
            payload.transcript, payload.selected_block_id
        )
        return VoiceDecideResponse(
            transcript=payload.transcript,
            decision_summary=f"Action: {decision.action}",
            actions=[decision.model_dump()],
            updated_trip_plan=trip,
            needs_clarification=(decision.action == "none"),
            options=[],
        )

    def apply_voice_intent(
        self, trip_id: str, filename: str, data: bytes
    ) -> VoiceIntentResponse:
        transcription = self.transcribe_audio(filename, data)
        decision = self._decide_with_openrouter(transcription.transcript, None)
        trip = self.get_trip(trip_id)
        if decision.action == "skip" and decision.block_id:
            trip = self.skip_block(trip_id, decision.block_id)
        elif decision.action == "change" and decision.block_id:
            trip = self.change_block(
                trip_id,
                decision.block_id,
                ChangeBlockInput(
                    preference_text=decision.preference_text,
                    direction=decision.direction,
                ),
            )
        return VoiceIntentResponse(
            transcript=transcription.transcript,
            decision=decision,
            agent_message="Voice command applied.",
            trip=trip,
        )

    def _search_with_web_agent(
        self,
        *,
        query_text: str,
        destination: str | None,
        constraints: dict[str, Any],
    ) -> list[dict[str, Any]]:
        from web_agent import gather_evidence

        result = gather_evidence(
            query_text=query_text,
            destination=destination,
            constraints=constraints,
        )
        return [
            {
                "id": item.evidence_id,
                "name": item.name,
                "summary": item.summary,
                "link": item.link,
                "source": item.source,
                "confidence": item.confidence,
            }
            for item in result.evidence
        ]

    def _decide_with_openrouter(
        self, transcript: str, selected_block_id: str | None
    ) -> VoiceDecision:
        api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        if not api_key:
            raise UpstreamDomainError("Voice intent failed")
        model = os.getenv("VOICE_DECIDE_MODEL", "openai/gpt-4.1-mini")
        base_url = os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/")
        prompt = (
            "Return strict JSON: {action, block_id, direction, preference_text}. "
            "action must be skip, change, or none. direction must be cheaper, closer, higher_rated, or null. "
            f"Transcript: {transcript}. Selected block: {selected_block_id}."
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a voice intent parser."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(
                    f"{base_url}/chat/completions", json=payload, headers=headers
                )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return VoiceDecision.model_validate(parsed)
        except Exception as exc:  # noqa: BLE001
            raise UpstreamDomainError("Voice intent failed") from exc

    def _check_databricks(self) -> bool:
        try:
            from warehouse_db.databricks_repository import DatabricksSqlConfig
            from databricks import sql

            cfg = DatabricksSqlConfig.from_env()
            with sql.connect(
                server_hostname=cfg.server_hostname,
                http_path=cfg.http_path,
                access_token=cfg.access_token,
                catalog=cfg.catalog,
                schema=cfg.schema,
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    row = cursor.fetchone()
                    return bool(row and int(row[0]) == 1)
        except Exception:  # noqa: BLE001
            return False

    def _check_qdrant(self) -> bool:
        try:
            from qdrant_client import QdrantClient

            qdrant_url = os.getenv("QDRANT_URL")
            qdrant_api_key = os.getenv("QDRANT_API_KEY")
            if not qdrant_url or not qdrant_api_key:
                return False
            client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
            client.get_collections()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _check_anthropic(self) -> bool:
        try:
            from anthropic import Anthropic

            api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
            if not api_key:
                return False
            client = Anthropic(api_key=api_key)
            _ = client
            return True
        except Exception:  # noqa: BLE001
            return False

    def _check_openrouter(self) -> bool:
        api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        if not api_key:
            return False
        base_url = os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/")
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            return response.status_code < 400
        except Exception:  # noqa: BLE001
            return False

    def _compose_and_persist(
        self,
        *,
        trip_id: str,
        plan_request: PlanRequest,
        inputs: TripCreateInput,
        timezone: str,
        flight_search_id: str,
        attractions_search_id: str,
        existing_audit: list[ChangeEvent] | None = None,
        existing_transit: list[ItineraryBlock] | None = None,
    ) -> TripPlan:
        try:
            response = self.orchestrator.run(plan_request)
        except ValueError as exc:
            raise ValidationDomainError(str(exc)) from exc
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UpstreamDomainError("Upstream dependency failure.") from exc

        trip = map_itinerary_to_trip_plan(
            itinerary=response.itinerary,
            trip_id=trip_id,
            inputs=inputs,
            timezone=timezone,
            search_refs=SearchRefs(
                flight_search_id=flight_search_id,
                attractions_search_id=attractions_search_id,
            ),
            audit_log=existing_audit or [],
            transit=existing_transit or [],
        )
        try:
            self.repository.save_trip_record(
                TripRecord(
                    trip=trip,
                    itinerary=response.itinerary,
                    plan_request=plan_request,
                    timezone=timezone,
                )
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RepositoryDomainError("Failed to persist trip record.") from exc
        return trip

    def _get_trip_record_optional(self, trip_id: str) -> TripRecord | None:
        try:
            return self.repository.get_trip_record(trip_id)
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RepositoryDomainError("Failed to load trip record.") from exc

    def _get_trip_record_required(self, trip_id: str) -> TripRecord:
        record = self._get_trip_record_optional(trip_id)
        if record is None:
            raise NotFoundDomainError(f"Trip '{trip_id}' was not found.")
        return record

    def _save_trip_record(self, previous: TripRecord, trip: TripPlan) -> None:
        try:
            self.repository.save_trip_record(
                TripRecord(
                    trip=trip,
                    itinerary=previous.itinerary,
                    plan_request=previous.plan_request,
                    timezone=previous.timezone,
                )
            )
        except DomainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RepositoryDomainError("Failed to persist trip record.") from exc

    def _find_block(self, trip: TripPlan, block_id: str):
        for day in trip.itinerary:
            for block in day.blocks:
                if block.block_id == block_id:
                    return block
        for block in trip.transit:
            if block.block_id == block_id:
                return block
        return None
