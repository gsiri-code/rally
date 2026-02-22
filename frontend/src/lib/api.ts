import type { TripPlan, TripFormInputs, ChangeBlockPayload, VoiceIntentResponse, Block, Day } from "./types";

const BASE = import.meta.env.VITE_RALLY_API_BASE || "http://localhost:8080";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${text || res.statusText}`);
  }
  return res.json();
}

/** Map API response shape to our frontend TripPlan shape */
function normalizeTripPlan(raw: any): TripPlan {
  const days: Day[] = (raw.itinerary ?? raw.days ?? []).map((d: any) => ({
    date: d.date,
    blocks: (d.blocks ?? []).map((b: any): Block => ({
      block_id: b.block_id,
      title: b.title,
      kind: b.kind,
      status: b.status,
      start_time: b.start_time ?? b.start_at,
      end_time: b.end_time ?? b.end_at,
      place_ref: b.place_ref,
      meta: b.meta,
      notes: b.notes,
    })),
  }));

  // Merge transit (flights) into days by start date
  const transitBlocks: Block[] = (raw.transit ?? []).map((b: any): Block => ({
    block_id: b.block_id,
    title: b.title,
    kind: b.kind,
    status: b.status,
    start_time: b.start_time ?? b.start_at,
    end_time: b.end_time ?? b.end_at,
    place_ref: b.place_ref,
    meta: b.meta,
    notes: b.notes,
  }));

  for (const tb of transitBlocks) {
    const tbDate = tb.start_time.slice(0, 10); // YYYY-MM-DD
    let day = days.find((d) => d.date === tbDate);
    if (!day) {
      // Create a new day for this transit block
      day = { date: tbDate, blocks: [] };
      days.push(day);
    }
    // Only add if not already present
    if (!day.blocks.some((b) => b.block_id === tb.block_id)) {
      day.blocks.push(tb);
    }
  }

  // Sort days by date, and blocks within each day by start_time
  days.sort((a, b) => a.date.localeCompare(b.date));
  for (const d of days) {
    d.blocks.sort((a, b) => a.start_time.localeCompare(b.start_time));
  }

  return {
    trip_id: raw.trip_id,
    timezone: raw.timezone,
    origin: raw.inputs?.origin ?? raw.origin ?? "",
    destinations: raw.inputs?.destinations ?? raw.destinations ?? [],
    start_date: raw.inputs?.start_date ?? raw.start_date ?? "",
    end_date: raw.inputs?.end_date ?? raw.end_date ?? "",
    budget_level: raw.inputs?.budget_level ?? raw.budget_level ?? "mid",
    interests: raw.inputs?.interests ?? raw.interests ?? [],
    neighborhoods: raw.inputs?.neighborhoods ?? raw.neighborhoods ?? [],
    days,
  };
}

export async function createTrip(input: TripFormInputs): Promise<TripPlan> {
  const res = await fetch(`${BASE}/v1/trips`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const raw = await json<any>(res);
  return normalizeTripPlan(raw);
}

export async function skipBlock(tripId: string, blockId: string): Promise<TripPlan> {
  const res = await fetch(`${BASE}/v1/trips/${tripId}/blocks/${blockId}/skip`, {
    method: "POST",
  });
  const raw = await json<any>(res);
  return normalizeTripPlan(raw);
}

export async function changeBlock(
  tripId: string,
  blockId: string,
  payload: ChangeBlockPayload
): Promise<TripPlan> {
  const res = await fetch(`${BASE}/v1/trips/${tripId}/blocks/${blockId}/change`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const raw = await json<any>(res);
  return normalizeTripPlan(raw);
}

export async function getTrip(tripId: string): Promise<TripPlan> {
  const res = await fetch(`${BASE}/v1/trips/${tripId}`);
  const raw = await json<any>(res);
  return normalizeTripPlan(raw);
}

export async function voiceIntent(tripId: string, audioBlob: Blob): Promise<VoiceIntentResponse> {
  const form = new FormData();
  form.append("trip_id", tripId);
  form.append("audio", new File([audioBlob], "voice.wav", { type: "audio/wav" }));
  const res = await fetch(`${BASE}/v1/voice/intent`, {
    method: "POST",
    body: form,
  });
  const raw = await json<any>(res);
  return { ...raw, trip: normalizeTripPlan(raw.trip) };
}

export async function downloadCalendar(tripId: string): Promise<Blob> {
  const res = await fetch(`${BASE}/v1/trips/${tripId}/calendar.ics`);
  if (!res.ok) throw new Error(`Calendar download failed: ${res.status}`);
  return res.blob();
}
