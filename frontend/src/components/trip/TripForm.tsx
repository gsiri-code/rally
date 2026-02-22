import { useState } from "react";
import { format } from "date-fns";
import { CalendarIcon, Plane, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import type { TripFormInputs, BudgetLevel } from "@/lib/types";

const INTERESTS = ["art", "food", "nightlife", "history", "outdoors", "shopping"] as const;
const BUDGET_MAP: Record<number, BudgetLevel> = { 0: "low", 1: "mid", 2: "high" };
const BUDGET_LABELS: Record<number, string> = { 0: "Budget", 1: "Moderate", 2: "Premium" };

interface TripFormProps {
  initialInputs?: TripFormInputs | null;
  onSubmit: (inputs: TripFormInputs) => Promise<void>;
  loading: boolean;
}

export default function TripForm({ initialInputs, onSubmit, loading }: TripFormProps) {
  const [startDate, setStartDate] = useState<Date | undefined>(
    initialInputs?.start_date ? new Date(initialInputs.start_date) : undefined
  );
  const [endDate, setEndDate] = useState<Date | undefined>(
    initialInputs?.end_date ? new Date(initialInputs.end_date) : undefined
  );
  const [origin, setOrigin] = useState(initialInputs?.origin || "");
  const [destination, setDestination] = useState(initialInputs?.destinations?.[0] || "");
  const [budgetIdx, setBudgetIdx] = useState(
    initialInputs ? (["low", "mid", "high"].indexOf(initialInputs.budget_level)) : 1
  );
  const [interests, setInterests] = useState<string[]>(initialInputs?.interests || []);
  const [neighborhoodsRaw, setNeighborhoodsRaw] = useState(
    initialInputs?.neighborhoods?.join(", ") || ""
  );

  const toggleInterest = (val: string) => {
    setInterests((prev) =>
      prev.includes(val) ? prev.filter((i) => i !== val) : [...prev, val]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!startDate || !endDate || !origin || !destination) return;

    const inputs: TripFormInputs = {
      start_date: format(startDate, "yyyy-MM-dd"),
      end_date: format(endDate, "yyyy-MM-dd"),
      origin: origin.toUpperCase(),
      destinations: [destination.toUpperCase()],
      budget_level: BUDGET_MAP[budgetIdx],
      interests,
      neighborhoods: neighborhoodsRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    await onSubmit(inputs);
  };

  return (
    <Card className="border-border/60 shadow-sm">
      <CardHeader className="pb-4">
        <CardTitle className="flex items-center gap-2 text-xl">
          <Plane className="h-5 w-5 text-primary" />
          Plan Your Trip
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Dates */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Start date</Label>
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    className={cn(
                      "w-full justify-start text-left font-normal",
                      !startDate && "text-muted-foreground"
                    )}
                  >
                    <CalendarIcon className="mr-2 h-4 w-4" />
                    {startDate ? format(startDate, "PPP") : "Pick a date"}
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="single"
                    selected={startDate}
                    onSelect={setStartDate}
                    initialFocus
                    className="p-3 pointer-events-auto"
                  />
                </PopoverContent>
              </Popover>
            </div>
            <div className="space-y-2">
              <Label>End date</Label>
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    className={cn(
                      "w-full justify-start text-left font-normal",
                      !endDate && "text-muted-foreground"
                    )}
                  >
                    <CalendarIcon className="mr-2 h-4 w-4" />
                    {endDate ? format(endDate, "PPP") : "Pick a date"}
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="single"
                    selected={endDate}
                    onSelect={setEndDate}
                    initialFocus
                    className="p-3 pointer-events-auto"
                  />
                </PopoverContent>
              </Popover>
            </div>
          </div>

          {/* Origin / Dest */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Origin (IATA)</Label>
              <Input
                placeholder="JFK"
                value={origin}
                onChange={(e) => setOrigin(e.target.value)}
                maxLength={4}
                className="uppercase"
              />
            </div>
            <div className="space-y-2">
              <Label>Destination (IATA)</Label>
              <Input
                placeholder="LHR"
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
                maxLength={4}
                className="uppercase"
              />
            </div>
          </div>

          {/* Budget */}
          <div className="space-y-3">
            <Label>
              Budget: <Badge variant="secondary" className="ml-1">{BUDGET_LABELS[budgetIdx]}</Badge>
            </Label>
            <Slider
              value={[budgetIdx]}
              onValueChange={([v]) => setBudgetIdx(v)}
              min={0}
              max={2}
              step={1}
              className="w-full"
            />
          </div>

          {/* Interests */}
          <div className="space-y-3">
            <Label>Interests</Label>
            <div className="flex flex-wrap gap-3">
              {INTERESTS.map((int) => (
                <label
                  key={int}
                  className="flex items-center gap-2 cursor-pointer"
                >
                  <Checkbox
                    checked={interests.includes(int)}
                    onCheckedChange={() => toggleInterest(int)}
                  />
                  <span className="text-sm capitalize">{int}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Neighborhoods */}
          <div className="space-y-2">
            <Label>Neighborhoods (comma-separated, optional)</Label>
            <Input
              placeholder="Soho, Shoreditch, Camden"
              value={neighborhoodsRaw}
              onChange={(e) => setNeighborhoodsRaw(e.target.value)}
            />
          </div>

          <Button
            type="submit"
            className="w-full"
            disabled={loading || !startDate || !endDate || !origin || !destination}
          >
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Generating…
              </>
            ) : (
              "Generate Trip"
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
