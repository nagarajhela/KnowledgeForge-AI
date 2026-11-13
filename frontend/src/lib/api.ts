const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export interface ApiOptions extends RequestInit {
  token?: string | null;
  organizationId?: string | null;
}

export async function apiFetch<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const headers = new Headers(opts.headers);
  if (opts.token) {
    headers.set("Authorization", `Bearer ${opts.token}`);
  }
  if (opts.organizationId) {
    headers.set("X-Organization-ID", opts.organizationId);
  }
  if (!(opts.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody?.error?.message || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function getStreamUrl(sessionId: string, question: string): string {
  const params = new URLSearchParams({ question });
  return `${API_BASE}/chat/sessions/${sessionId}/stream?${params.toString()}`;
}
