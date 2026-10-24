const KEY = "keel.llmKey";

export type Conversation = {
  id: string;
  channel: string;
  status: string;
  outcome: string;
  subject: string | null;
  customer_name: string | null;
  customer_email: string | null;
  verified_order_number: string | null;
  verified_via: string | null;
  sentiment: string;
  last_intent: string | null;
  updated_at: string;
  preview: string;
};

export type Hit = {
  article_id: string;
  title: string;
  section: string;
  text: string;
  cosine: number;
  bm25: number;
  rerank: number;
  overlap?: number;
  gate?: string;
};

export type Trace = {
  states: string[];
  intent: string;
  sentiment: string;
  mode?: string;
  injection: boolean;
  social: boolean;
  retrieval: Hit[];
  tools: { name: string; arguments: Record<string, unknown>; ok: boolean; result: Record<string, unknown> }[];
  guardrails: { rule: string; decision: string; detail: string }[];
  identity: { verified: boolean; method: string | null; order_number: string | null };
  outcome?: string;
};

export type Ticket = {
  id: string;
  conversation_id: string;
  reason: string;
  summary: string;
  intent: string;
  sentiment: string;
  actions: string[];
  zendesk_id: string | null;
  status: string;
  created_at: string;
  transcript: string;
  channel?: string | null;
  customer_name?: string | null;
  customer_email?: string | null;
};

export type Detail = Conversation & {
  messages: { id: string; role: string; content: string; created_at: string; trace: Trace | null }[];
  tickets: Ticket[];
  csat: string | null;
};

export type Metrics = {
  conversations: number;
  open: number;
  closed: number;
  deflected: number;
  handed_off: number;
  deflection_rate: number | null;
  handoff_reasons: Record<string, number>;
  csat_up: number;
  csat_down: number;
  csat_total: number;
  csat_rate: number | null;
  outcomes: Record<string, number>;
  definition: string;
};

export type Article = { id: string; title: string; source_type: string; source_name: string };
export type ArticleDetail = Article & { body: string; sections: { section: string; text: string }[] };
export type Fixture = { number: string; email: string; postcode: string; status: string; total_cents: number; note: string };
export type Health = { ok: boolean; articles: number; orders: number; conversations: number; server_llm: boolean };

export function llmKey() {
  return sessionStorage.getItem(KEY) || "";
}

export function setLlmKey(value: string) {
  if (value.trim()) sessionStorage.setItem(KEY, value.trim());
  else sessionStorage.removeItem(KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const key = llmKey();
  if (key) headers.set("X-Keel-LLM-Key", key);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      /* keep status text */
    }
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return response.json() as Promise<T>;
}

export const getHealth = () => request<Health>("/api/health");
export const getConversations = () => request<Conversation[]>("/api/conversations");
export const getConversation = (id: string) => request<Detail>(`/api/conversations/${id}`);
export const getInbox = () => request<Ticket[]>("/api/inbox");
export const handleTicket = (id: string) => request<Ticket>(`/api/inbox/${id}/handle`, { method: "POST" });
export const getMetrics = () => request<Metrics>("/api/metrics");
export const getArticles = () => request<Article[]>("/api/kb/articles");
export const getArticle = (id: string) => request<ArticleDetail>(`/api/kb/articles/${id}`);
export const searchKb = (q: string) => request<{ q: string; band: string; hits: Hit[] }>("/api/kb/search", { method: "POST", body: JSON.stringify({ q }) });
export const getFixtures = () => request<Fixture[]>("/api/demo/fixtures");

export function money(cents: number) {
  return `$${(cents / 100).toFixed(2)}`;
}

export function when(iso: string | null) {
  if (!iso) return "";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(iso));
}
