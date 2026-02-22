export type BudgetLevel = "low" | "mid" | "high";

export interface PlaceRef {
  name?: string;
  address?: string;
  maps_url?: string;
  lat?: number;
  lng?: number;
}

export interface BlockMeta {
  rating?: number;
  review_count?: number;
  price_tier?: string;
  [key: string]: unknown;
}

export interface Block {
  block_id: string;
  title: string;
  kind: string;
  status: "planned" | "skipped" | "replaced";
  start_time: string;
  end_time: string;
  place_ref?: PlaceRef;
  meta?: BlockMeta;
  notes?: string;
}

export interface Day {
  date: string;
  blocks: Block[];
}

export interface TripPlan {
  trip_id: string;
  timezone: string;
  origin: string;
  destinations: string[];
  start_date: string;
  end_date: string;
  budget_level: BudgetLevel;
  interests: string[];
  neighborhoods: string[];
  days: Day[];
}

export interface TripFormInputs {
  start_date: string;
  end_date: string;
  origin: string;
  destinations: string[];
  budget_level: BudgetLevel;
  interests: string[];
  neighborhoods: string[];
}

export interface ChangeBlockPayload {
  preference_text: string;
  direction?: "cheaper" | "closer" | "higher_rated";
}

export interface VoiceDecision {
  action: string;
  block_id?: string;
  direction?: string;
  preference_text?: string;
}

export interface VoiceIntentResponse {
  transcript: string;
  decision: VoiceDecision;
  agent_message: string;
  trip: TripPlan;
}

export interface TripPrefs {
  likedBlockIds: string[];
}
