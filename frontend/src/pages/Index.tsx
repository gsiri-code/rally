import { useState, useCallback, useEffect } from "react";
import { Trash2, Download, Save, MapPin, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/hooks/use-toast";
import TripForm from "@/components/trip/TripForm";
import Itinerary from "@/components/trip/Itinerary";
import TripMap from "@/components/trip/TripMap";
import VoiceRecorder from "@/components/trip/VoiceRecorder";
import * as api from "@/lib/api";
import { saveWithTTL, loadWithTTL, clearKeys, KEYS } from "@/lib/persist";
import type { TripPlan, TripFormInputs, TripPrefs } from "@/lib/types";

export default function Index() {
  const { toast } = useToast();
  const [trip, setTrip] = useState<TripPlan | null>(null);
  const [prefs, setPrefs] = useState<TripPrefs>({ likedBlockIds: [] });
  const [savedInputs, setSavedInputs] = useState<TripFormInputs | null>(null);
  const [loading, setLoading] = useState(false);
  const [hydrating, setHydrating] = useState(false);
  const [hoveredBlockId, setHoveredBlockId] = useState<string | null>(null);

  // Fetch trip by ID (always fresh from API)
  const fetchTrip = useCallback(async (tripId: string) => {
    try {
      const fresh = await api.getTrip(tripId);
      setTrip(fresh);
      return fresh;
    } catch (err: any) {
      console.error("Failed to fetch trip", err);
      // Trip no longer exists on server — clear stored ID
      clearKeys([KEYS.TRIP_ID]);
      setTrip(null);
      return null;
    }
  }, []);

  // Hydrate on mount — load trip_id from localStorage, fetch fresh data
  useEffect(() => {
    const tripId = loadWithTTL<string>(KEYS.TRIP_ID);
    const p = loadWithTTL<TripPrefs>(KEYS.PREFS);
    const i = loadWithTTL<TripFormInputs>(KEYS.INPUTS);
    if (p) setPrefs(p);
    if (i) setSavedInputs(i);
    // Clean up old keys
    clearKeys([KEYS.TRIP_PLAN]);
    if (tripId) {
      setHydrating(true);
      fetchTrip(tripId).finally(() => setHydrating(false));
    }
  }, [fetchTrip]);

  const persistTripId = useCallback((tripId: string) => {
    saveWithTTL(KEYS.TRIP_ID, tripId);
  }, []);

  const persistPrefs = useCallback((p: TripPrefs) => {
    setPrefs(p);
    saveWithTTL(KEYS.PREFS, p);
  }, []);

  // Form submit
  const handleCreate = async (inputs: TripFormInputs) => {
    setLoading(true);
    try {
      const plan = await api.createTrip(inputs);
      setTrip(plan);
      persistTripId(plan.trip_id);
      saveWithTTL(KEYS.INPUTS, inputs);
      setSavedInputs(inputs);
      toast({ title: "Trip generated!", description: `${plan.days.length} days planned.` });
    } catch (err: any) {
      toast({ title: "Error creating trip", description: err.message, variant: "destructive" });
    } finally {
      setLoading(false);
    }
  };

  // Like toggle
  const toggleLike = useCallback(
    (blockId: string) => {
      const liked = prefs.likedBlockIds.includes(blockId);
      const next: TripPrefs = {
        likedBlockIds: liked
          ? prefs.likedBlockIds.filter((id) => id !== blockId)
          : [...prefs.likedBlockIds, blockId],
      };
      persistPrefs(next);
    },
    [prefs, persistPrefs]
  );

  // Skip
  const handleSkip = async (blockId: string) => {
    if (!trip) return;
    const optimistic = {
      ...trip,
      days: trip.days.map((d) => ({
        ...d,
        blocks: d.blocks.map((b) =>
          b.block_id === blockId ? { ...b, status: "skipped" as const } : b
        ),
      })),
    };
    setTrip(optimistic);
    try {
      await api.skipBlock(trip.trip_id, blockId);
    } catch (err: any) {
      setTrip(trip);
      toast({ title: "Skip failed", description: err.message, variant: "destructive" });
    }
    await fetchTrip(trip.trip_id);
  };

  // Change
  const handleChange = async (blockId: string, text: string, direction?: string) => {
    if (!trip) return;
    try {
      await api.changeBlock(trip.trip_id, blockId, {
        preference_text: text,
        direction: direction as any,
      });
      toast({ title: "Block updated" });
    } catch (err: any) {
      toast({ title: "Change failed", description: err.message, variant: "destructive" });
    }
    await fetchTrip(trip.trip_id);
  };

  // Voice
  const handleVoice = async (blob: Blob) => {
    if (!trip) return;
    try {
      const res = await api.voiceIntent(trip.trip_id, blob);
      setTrip(res.trip);
      return res;
    } catch (err: any) {
      toast({ title: "Voice command failed", description: err.message, variant: "destructive" });
      return null;
    }
  };

  // Delete saved
  const handleDelete = () => {
    clearKeys([KEYS.TRIP_ID, KEYS.PREFS, KEYS.INPUTS]);
    setTrip(null);
    setPrefs({ likedBlockIds: [] });
    setSavedInputs(null);
    toast({ title: "Saved trip deleted" });
  };

  // Export calendar
  const handleExport = async () => {
    if (!trip) return;
    try {
      const blob = await api.downloadCalendar(trip.trip_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `trip-${trip.trip_id}.ics`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      toast({ title: "Export failed", description: err.message, variant: "destructive" });
    }
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b border-border/60 bg-card/80 backdrop-blur-sm sticky top-0 z-20">
        <div className="container max-w-7xl mx-auto flex items-center justify-between py-4 px-4">
          <div className="flex items-center gap-2">
            <MapPin className="h-5 w-5 text-primary" />
            <h1 className="text-lg font-semibold tracking-tight">Rally</h1>
          </div>
          <div className="flex items-center gap-2">
            {trip && (
              <>
                <Button variant="outline" size="sm" onClick={handleExport}>
                  <Download className="h-3.5 w-3.5 mr-1" />
                  Calendar
                </Button>
                <Button variant="outline" size="sm" onClick={handleDelete}>
                  <Trash2 className="h-3.5 w-3.5 mr-1" />
                  Delete
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="container max-w-7xl mx-auto px-4 py-8">
        {/* Loading on hydrate */}
        {hydrating && (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
            <span className="ml-2 text-sm text-muted-foreground">Loading your trip…</span>
          </div>
        )}

        {/* Form (full width when no trip) */}
        {!trip && !hydrating && (
          <div className="max-w-3xl mx-auto">
            <TripForm
              initialInputs={savedInputs}
              onSubmit={handleCreate}
              loading={loading}
            />
          </div>
        )}

        {/* Side-by-side layout when trip exists */}
        {trip && (
          <div className="flex gap-6">
            {/* Left: itinerary */}
            <div className="flex-1 min-w-0 space-y-8">
              {/* Voice */}
              <VoiceRecorder
                tripId={trip.trip_id}
                onResult={() => {}}
                onAudioReady={async (blob) => {
                  await handleVoice(blob);
                }}
              />

              {/* Itinerary */}
              <Itinerary
                trip={trip}
                prefs={prefs}
                onToggleLike={toggleLike}
                onSkip={handleSkip}
                onChange={handleChange}
                onHoverBlock={setHoveredBlockId}
              />

              {/* New trip form */}
              <div className="pt-4 border-t border-border/60">
                <p className="text-sm text-muted-foreground mb-4">
                  Want a different trip? Delete the current one or plan a new one below.
                </p>
                <TripForm
                  initialInputs={savedInputs}
                  onSubmit={handleCreate}
                  loading={loading}
                />
              </div>
            </div>

            {/* Right: sticky map */}
            <div className="hidden lg:block w-[440px] shrink-0">
              <div className="sticky top-20 h-[calc(100vh-6rem)]">
                <TripMap trip={trip} hoveredBlockId={hoveredBlockId} />
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
