export type ResolutionSource = "LIVE_INFERENCE" | "LLM_CACHE";

export interface ChatMetadata {
  resolution_source: ResolutionSource;
  model: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  key_id: string | null;
  fallback_attempts: number;
}

export interface ChatResponse {
  session_id: string;
  reply: string;
  metadata: ChatMetadata;
}

export interface Health {
  status: string;
  keys_configured: number;
  cache_enabled: boolean;
  models?: string[];
  failure_simulation?: boolean;
}

declare global {
  interface Window {
    __ENV__?: { API_URL?: string };
  }
}

// Docker serves /env.js generated from API_URL at container start; Vercel and
// local dev use VITE_API_URL at build time.
export const API_URL = (
  window.__ENV__?.API_URL ||
  import.meta.env.VITE_API_URL ||
  "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function describeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  // FastAPI validation errors: [{ loc: [...], msg: "..." }, ...]
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const field = Array.isArray(d?.loc) ? d.loc.filter((p: unknown) => p !== "body").join(".") : "";
        return field ? `${field}: ${d?.msg}` : String(d?.msg ?? d);
      })
      .join("; ");
  }
  return "unexpected error";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }

  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // non-JSON body, handled below
  }

  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new ApiError(res.status, detail !== undefined ? describeDetail(detail) : `HTTP ${res.status}`);
  }
  return body as T;
}

export function sendMessage(
  sessionId: string,
  message: string,
  options: { systemPrompt?: string; simulateFailure?: string } = {},
): Promise<ChatResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.simulateFailure) headers["X-Simulate-Failure"] = options.simulateFailure;

  const payload: Record<string, string> = { session_id: sessionId, message };
  if (options.systemPrompt !== undefined) payload.system_prompt = options.systemPrompt;

  return request<ChatResponse>("/chat", { method: "POST", headers, body: JSON.stringify(payload) });
}

export function getHealth(): Promise<Health> {
  return request<Health>("/health");
}
