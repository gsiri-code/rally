import { useState } from "react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import BlockCard from "./BlockCard";
import type { TripPlan, TripPrefs } from "@/lib/types";

interface ItineraryProps {
  trip: TripPlan;
  prefs: TripPrefs;
  onToggleLike: (blockId: string) => void;
  onSkip: (blockId: string) => Promise<void>;
  onChange: (blockId: string, text: string, direction?: string) => Promise<void>;
  onHoverBlock?: (blockId: string | null) => void;
}

export default function Itinerary({
  trip,
  prefs,
  onToggleLike,
  onSkip,
  onChange,
  onHoverBlock,
}: ItineraryProps) {
  const [likedOnly, setLikedOnly] = useState(false);

  const days = trip.days ?? [];
  const defaultOpen = days.map((_, i) => `day-${i}`);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="font-mono text-xs">
              {trip.trip_id}
            </Badge>
            <Badge variant="secondary" className="text-xs">
              {trip.timezone}
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Switch
            id="liked-only"
            checked={likedOnly}
            onCheckedChange={setLikedOnly}
          />
          <Label htmlFor="liked-only" className="text-sm">
            Liked only
          </Label>
        </div>
      </div>

      {/* Days */}
      <Accordion type="multiple" defaultValue={defaultOpen}>
        {days.map((day, i) => {
          // Find flight windows to hide overlapping/conflicting blocks
          const flights = day.blocks.filter((b) => b.kind === "flight");
          const visibleBlocks = day.blocks.filter((b) => {
            if (b.kind === "flight") return true;
            // Hide blocks that overlap with any flight's time range
            return !flights.some(
              (f) => b.start_time < f.end_time && b.end_time > f.start_time
            );
          });

          const blocks = likedOnly
            ? visibleBlocks.filter((b) => prefs.likedBlockIds.includes(b.block_id))
            : visibleBlocks;

          return (
            <AccordionItem value={`day-${i}`} key={day.date}>
              <AccordionTrigger className="text-sm font-medium">
                <span className="flex items-center gap-2">
                  Day {i + 1}
                  <span className="text-muted-foreground font-normal">
                    — {new Date(day.date + "T00:00:00").toLocaleDateString("en-US", {
                      weekday: "short",
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                  <Badge variant="secondary" className="text-xs">
                    {blocks.length} blocks
                  </Badge>
                </span>
              </AccordionTrigger>
              <AccordionContent>
                <div className="space-y-2 pt-2">
                  {blocks.length === 0 ? (
                    <p className="text-sm text-muted-foreground py-4 text-center">
                      {likedOnly ? "No liked blocks this day" : "No blocks"}
                    </p>
                  ) : (
                    blocks.map((block) => (
                      <div
                        key={block.block_id}
                        onMouseEnter={() => onHoverBlock?.(block.block_id)}
                        onMouseLeave={() => onHoverBlock?.(null)}
                      >
                        <BlockCard
                          block={block}
                          timezone={trip.timezone}
                          liked={prefs.likedBlockIds.includes(block.block_id)}
                          onToggleLike={onToggleLike}
                          onSkip={onSkip}
                          onChange={onChange}
                        />
                      </div>
                    ))
                  )}
                </div>
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>
    </div>
  );
}
