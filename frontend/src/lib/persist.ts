const TTL_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

interface Envelope<T> {
  value: T;
  savedAt: number;
}

export function saveWithTTL<T>(key: string, value: T, days = 30): void {
  const envelope: Envelope<T> = {
    value,
    savedAt: Date.now(),
  };
  localStorage.setItem(key, JSON.stringify(envelope));
}

export function loadWithTTL<T>(key: string): T | null {
  const raw = localStorage.getItem(key);
  if (!raw) return null;
  try {
    const envelope: Envelope<T> = JSON.parse(raw);
    if (Date.now() - envelope.savedAt > TTL_MS) {
      localStorage.removeItem(key);
      return null;
    }
    return envelope.value;
  } catch {
    localStorage.removeItem(key);
    return null;
  }
}

export function clearKeys(keys: string[]): void {
  keys.forEach((k) => localStorage.removeItem(k));
}

export const KEYS = {
  TRIP_ID: "rally_trip_id_v2",
  PREFS: "rally_trip_prefs_v1",
  INPUTS: "rally_trip_inputs_v1",
  /** @deprecated kept for cleanup of old data */
  TRIP_PLAN: "rally_trip_plan_v1",
} as const;
