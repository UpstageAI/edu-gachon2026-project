export type StreamEventType =
  | "session"
  | "parsed"
  | "stats"
  | "citation"
  | "token"
  | "escalate"
  | "reask"
  | "error"
  | "degraded"
  | "done"
  | "thinking";

export interface ChatStreamRequest {
  message: string;
  threadId?: string;
}

export interface ParsedStreamData {
  region?: string;
  month?: string;
  companions?: string;
  intent?: string;
  disaster_type?: string | null;
}

export interface RiskScore {
  disaster_type: string;
  risk_score: number;
  count: number;
}

export interface StatsStreamData {
  scope_used?: string;
  total_count?: number;
  risk_scores?: RiskScore[];
  top_risk?: string;
  fallback_notice?: string | null;
}

export interface CitationStreamData {
  ids: string[];
}

export interface ContactData {
  agency?: string;
  phone?: string;
}

export interface SessionStreamData {
  thread_id?: string;
}

export interface EscalateStreamData {
  reason?: string;
  message?: string;
  contact?: ContactData;
}

export interface ReaskStreamData {
  message?: string;
}

export interface ErrorStreamData {
  message?: string;
  detail?: string;
  contact?: ContactData;
}

export interface DegradedStreamData {
  reason?: string;
  message?: string;
  contact?: ContactData;
}

export type StreamEventData =
  | SessionStreamData
  | ParsedStreamData
  | StatsStreamData
  | CitationStreamData
  | EscalateStreamData
  | ReaskStreamData
  | ErrorStreamData
  | DegradedStreamData
  | Record<string, unknown>;

export interface StreamEvent {
  type: StreamEventType;
  content?: string;
  status?: string;
  data?: StreamEventData;
  toolUsed?: string;
}
