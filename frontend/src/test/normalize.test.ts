import { describe, it, expect } from "vitest";

// Inline the normalization logic for testing since it's not exported
function normalizeTripPlan(raw: any) {
  const days: any[] = (raw.itinerary ?? raw.days ?? []).map((d: any) => ({
    date: d.date,
    blocks: (d.blocks ?? []).map((b: any) => ({
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

  const transitBlocks: any[] = (raw.transit ?? []).map((b: any) => ({
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
    const tbDate = tb.start_time.slice(0, 10);
    let day = days.find((d) => d.date === tbDate);
    if (!day) {
      day = { date: tbDate, blocks: [] };
      days.push(day);
    }
    if (!day.blocks.some((b: any) => b.block_id === tb.block_id)) {
      day.blocks.push(tb);
    }
  }

  days.sort((a: any, b: any) => a.date.localeCompare(b.date));
  for (const d of days) {
    d.blocks.sort((a: any, b: any) => a.start_time.localeCompare(b.start_time));
  }

  return { days };
}

describe("normalizeTripPlan transit merge", () => {
  it("merges transit flights into matching days", () => {
    const raw = {
      itinerary: [
        {
          date: "2026-02-22",
          blocks: [
            { block_id: "b1", title: "Prep", kind: "free_time", status: "planned", start_at: "2026-02-22T18:00:00+01:00", end_at: "2026-02-22T22:00:00+01:00" },
          ],
        },
        {
          date: "2026-02-23",
          blocks: [
            { block_id: "b2", title: "Museum", kind: "attraction", status: "planned", start_at: "2026-02-23T14:00:00+01:00", end_at: "2026-02-23T16:00:00+01:00" },
          ],
        },
      ],
      transit: [
        {
          block_id: "f1",
          title: "Flight DL126",
          kind: "flight",
          status: "planned",
          start_at: "2026-02-23T00:55:00+01:00",
          end_at: "2026-02-23T12:10:00+01:00",
        },
      ],
    };

    const result = normalizeTripPlan(raw);

    // Flight should be in day 2026-02-23
    const day23 = result.days.find((d: any) => d.date === "2026-02-23");
    expect(day23).toBeDefined();
    const flightBlock = day23!.blocks.find((b: any) => b.block_id === "f1");
    expect(flightBlock).toBeDefined();
    expect(flightBlock.kind).toBe("flight");
    expect(flightBlock.title).toBe("Flight DL126");
    // Flight should come before the museum (sorted by start_time)
    expect(day23!.blocks[0].block_id).toBe("f1");
  });

  it("creates a new day if transit date doesn't match any existing day", () => {
    const raw = {
      itinerary: [
        { date: "2026-02-22", blocks: [] },
      ],
      transit: [
        {
          block_id: "f1",
          title: "Flight Return",
          kind: "flight",
          status: "planned",
          start_at: "2026-02-25T21:30:00+01:00",
          end_at: "2026-02-26T06:00:00+01:00",
        },
      ],
    };

    const result = normalizeTripPlan(raw);
    expect(result.days).toHaveLength(2);
    const day25 = result.days.find((d: any) => d.date === "2026-02-25");
    expect(day25).toBeDefined();
    expect(day25!.blocks[0].kind).toBe("flight");
  });
});
