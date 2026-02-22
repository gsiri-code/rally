import { useState } from "react";
import {
  Heart,
  MapPin,
  Star,
  SkipForward,
  RefreshCw,
  Loader2,
  Plane,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import type { Block } from "@/lib/types";

const KIND_COLORS: Record<string, string> = {
  flight: "bg-[hsl(var(--travel-flight))] text-[hsl(var(--travel-flight-foreground))]",
  cafe: "bg-accent text-accent-foreground",
  attraction: "bg-travel-sky text-foreground",
  lunch: "bg-secondary text-secondary-foreground",
  dinner: "bg-secondary text-secondary-foreground",
  free_time: "bg-muted text-muted-foreground",
};

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  planned: "outline",
  skipped: "secondary",
  replaced: "default",
};

function formatTime(iso: string, timezone: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", {
      timeZone: timezone,
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return iso;
  }
}

interface BlockCardProps {
  block: Block;
  timezone: string;
  liked: boolean;
  onToggleLike: (blockId: string) => void;
  onSkip: (blockId: string) => Promise<void>;
  onChange: (blockId: string, text: string, direction?: string) => Promise<void>;
}

export default function BlockCard({
  block,
  timezone,
  liked,
  onToggleLike,
  onSkip,
  onChange,
}: BlockCardProps) {
  const [changeOpen, setChangeOpen] = useState(false);
  const [prefText, setPrefText] = useState("");
  const [direction, setDirection] = useState<string>("");
  const [skipLoading, setSkipLoading] = useState(false);
  const [changeLoading, setChangeLoading] = useState(false);

  const handleSkip = async () => {
    setSkipLoading(true);
    try {
      await onSkip(block.block_id);
    } finally {
      setSkipLoading(false);
    }
  };

  const handleChange = async () => {
    if (!prefText.trim()) return;
    setChangeLoading(true);
    try {
      await onChange(block.block_id, prefText, direction || undefined);
      setChangeOpen(false);
      setPrefText("");
      setDirection("");
    } finally {
      setChangeLoading(false);
    }
  };

  const kindClass = KIND_COLORS[block.kind] || "bg-muted text-muted-foreground";
  const isFlight = block.kind === "flight";

  return (
    <>
      <Card className={`shadow-sm hover:shadow-md transition-shadow ${isFlight ? "border-[hsl(var(--travel-flight))]/40 bg-[hsl(var(--travel-flight-bg))]" : "border-border/50"}`}>
        <CardContent className="p-4">
          <div className="flex items-start justify-between gap-3">
            {/* Timeline dot + content */}
            <div className="flex gap-3 flex-1 min-w-0">
              <div className="flex flex-col items-center pt-1">
                {isFlight ? (
                  <Plane className="h-4 w-4 text-[hsl(var(--travel-flight))] shrink-0" />
                ) : (
                  <div className="w-2.5 h-2.5 rounded-full bg-primary shrink-0" />
                )}
                <div className="w-px flex-1 bg-border mt-1" />
              </div>
              <div className="flex-1 min-w-0 space-y-2">
                {/* Time */}
                <p className="text-xs text-muted-foreground">
                  {formatTime(block.start_time, timezone)} –{" "}
                  {formatTime(block.end_time, timezone)}
                </p>
                {/* Title + badges */}
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="font-medium text-sm">{block.title}</h4>
                  <Badge className={kindClass} variant="secondary">
                    {block.kind.replace("_", " ")}
                  </Badge>
                  {block.status !== "planned" && (
                    <Badge variant={STATUS_VARIANT[block.status]}>
                      {block.status}
                    </Badge>
                  )}
                </div>
                {/* Place */}
                {block.place_ref?.address && (
                  <div className="flex items-center gap-1 text-xs text-muted-foreground">
                    <MapPin className="h-3 w-3 shrink-0" />
                    <span className="truncate">{block.place_ref.address}</span>
                    {block.place_ref.maps_url && (
                      <a
                        href={block.place_ref.maps_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary underline underline-offset-2 ml-1 shrink-0"
                      >
                        Open in Maps
                      </a>
                    )}
                  </div>
                )}
                {/* Meta */}
                {block.meta && (
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    {block.meta.rating != null && (
                      <span className="flex items-center gap-0.5">
                        <Star className="h-3 w-3 fill-warning text-warning" />
                        {block.meta.rating}
                        {block.meta.review_count != null && (
                          <span className="ml-0.5">({block.meta.review_count})</span>
                        )}
                      </span>
                    )}
                    {block.meta.price_tier && (
                      <span>{block.meta.price_tier}</span>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-1 shrink-0">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => onToggleLike(block.block_id)}
              >
                <Heart
                  className={`h-4 w-4 transition-colors ${
                    liked
                      ? "fill-travel-sunset text-travel-sunset"
                      : "text-muted-foreground"
                  }`}
                />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={handleSkip}
                disabled={skipLoading || block.status === "skipped"}
              >
                {skipLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <SkipForward className="h-4 w-4 text-muted-foreground" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => setChangeOpen(true)}
              >
                <RefreshCw className="h-4 w-4 text-muted-foreground" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Change Dialog */}
      <Dialog open={changeOpen} onOpenChange={setChangeOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Change: {block.title}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>What do you want instead?</Label>
              <Textarea
                placeholder="Something more local and authentic…"
                value={prefText}
                onChange={(e) => setPrefText(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Direction (optional)</Label>
              <Select value={direction} onValueChange={setDirection}>
                <SelectTrigger>
                  <SelectValue placeholder="Any" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="cheaper">Cheaper</SelectItem>
                  <SelectItem value="closer">Closer</SelectItem>
                  <SelectItem value="higher_rated">Higher rated</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setChangeOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleChange} disabled={changeLoading || !prefText.trim()}>
              {changeLoading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Apply Change
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
