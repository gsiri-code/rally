## orchestrator_agent

LangGraph-based orchestration layer for itinerary planning.

Responsibilities:
- route phase transitions and retries
- trigger research fallback only on low/stale evidence
- always run research image enrichment for itinerary segments
- integrate with tool layer contracts (RAG + transcription)

### CLI

Print contract schemas:

```bash
orchestrator-agent --show-contracts
```

Run with user text (planner/research adapters are placeholders until implemented):

```bash
orchestrator-agent --text "3 days in Paris, art-focused"
```
