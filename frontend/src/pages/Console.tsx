import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getConversation, getConversations, when, type Conversation, type Detail, type Trace } from "../api.ts";
import { Empty } from "../Empty.tsx";

export function Console() {
  const { id } = useParams();
  const [rows, setRows] = useState<Conversation[] | null>(null);
  const [error, setError] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [detailError, setDetailError] = useState("");

  useEffect(() => {
    let stop = false;
    async function load() {
      try {
        const data = await getConversations();
        if (!stop) {
          setRows(data);
          setError("");
        }
      } catch (err) {
        if (!stop) setError(err instanceof Error ? err.message : "The Keel API is not responding.");
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!id) {
      setDetail(null);
      return;
    }
    let stop = false;
    setDetailError("");
    getConversation(id)
      .then((data) => {
        if (!stop) setDetail(data);
      })
      .catch((err: unknown) => {
        if (!stop) setDetailError(err instanceof Error ? err.message : "Could not load that conversation.");
      });
    const timer = window.setInterval(() => {
      getConversation(id)
        .then((data) => {
          if (!stop) setDetail(data);
        })
        .catch(() => undefined);
    }, 4000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [id]);

  const latestTrace = [...(detail?.messages || [])].reverse().find((message) => message.trace)?.trace || null;

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)] xl:grid-cols-[320px_minmax(0,1fr)_340px]">
      <section className={`${id ? "hidden lg:flex" : "flex"} min-h-0 flex-col border-r border-line`}>
        <header className="border-b border-line px-4 py-3">
          <h1 className="text-lg font-bold">Conversations</h1>
          <p className="text-sm text-muted">{rows ? `${rows.length} stored` : "Loading"}</p>
        </header>
        <div className="min-h-0 flex-1 overflow-auto">
          {error ? <p className="p-4 text-sm text-danger">{error} Start the API on port 8841 and refresh.</p> : null}
          {rows && rows.length === 0 ? (
            <div className="p-4">
              <Empty title="No conversations yet">Open the shop preview and send a message, or post a signed email to the webhook. Threads show up here with the customer’s words and Keel’s reply.</Empty>
            </div>
          ) : null}
          {rows === null && !error ? <p className="p-4 text-sm text-muted">Loading conversations</p> : null}
          <ul>
            {(rows || []).map((row) => (
              <li key={row.id}>
                <Link
                  to={`/conversations/${row.id}`}
                  className={`block border-b border-line px-4 py-3 no-underline ${id === row.id ? "bg-yellow text-[#141816]" : "text-ink hover:bg-sheet"}`}
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="font-bold">{row.customer_name || (row.channel === "email" ? row.customer_email : "Website visitor")}</span>
                    <time className="shrink-0 text-xs tabular-nums">{when(row.updated_at)}</time>
                  </div>
                  <p className="mt-1 text-xs uppercase tracking-normal">{labelStatus(row.status)} · {row.channel}</p>
                  <p className="mt-1 line-clamp-2 text-sm">{row.preview}</p>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>
      <section className={`${id ? "flex" : "hidden lg:flex"} min-h-0 flex-col bg-sheet`}>
        {!id ? (
          <div className="p-6">
            <Empty title="No thread open">Select a conversation. Each reply keeps the path it took: identity, tools, retrieved sections, and the guardrail that fired.</Empty>
          </div>
        ) : null}
        {detailError ? <p className="p-4 text-sm text-danger">{detailError}</p> : null}
        {id && detail ? (
          <>
            <header className="border-b border-line px-4 py-3">
              <Link to="/" className="text-sm text-ink underline lg:hidden">
                All conversations
              </Link>
              <h2 className="text-lg font-bold">{detail.customer_name || "Unverified visitor"}</h2>
              <p className="text-sm text-muted">
                {labelStatus(detail.status)}
                {detail.verified_order_number ? ` · ${detail.verified_order_number}` : ""}
                {detail.csat ? ` · CSAT ${detail.csat}` : ""}
              </p>
            </header>
            <div className="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-4">
              {detail.messages.map((message) => (
                <article key={message.id} className={message.role === "customer" ? "ml-8" : "mr-8"}>
                  <p className="text-xs text-muted">
                    {message.role === "customer" ? "Customer" : "Keel"} · {when(message.created_at)}
                  </p>
                  <p className={`mt-1 rounded-xl px-3 py-2 text-sm leading-6 ${message.role === "customer" ? "bg-pine text-foam" : "bg-canvas text-ink"}`}>
                    {message.content}
                  </p>
                </article>
              ))}
              <div className="xl:hidden">
                <h3 className="mt-6 mb-2 text-sm font-bold">Trace</h3>
                <TraceView trace={latestTrace} />
              </div>
            </div>
          </>
        ) : null}
      </section>
      <aside className="hidden min-h-0 flex-col border-l border-line xl:flex">
        <header className="border-b border-line px-4 py-3">
          <h2 className="text-lg font-bold">Trace</h2>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-4">
          {id ? <TraceView trace={latestTrace} /> : <Empty title="No trace yet">Retrieval, tool calls, and guardrail decisions appear here for the latest reply.</Empty>}
        </div>
      </aside>
    </div>
  );
}

export function TraceView({ trace }: { trace: Trace | null }) {
  if (!trace) return <p className="text-sm text-muted">No trace on this turn.</p>;
  return (
    <div className="space-y-4 text-sm">
      <p>
        <span className="text-muted">Path </span>
        {trace.states.join(" → ")}
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-muted">Intent</dt>
        <dd>{trace.intent}</dd>
        <dt className="text-muted">Sentiment</dt>
        <dd>{trace.sentiment}</dd>
        <dt className="text-muted">Mode</dt>
        <dd>{trace.mode || "demo"}</dd>
        <dt className="text-muted">Identity</dt>
        <dd>{trace.identity?.verified ? `${trace.identity.method} · ${trace.identity.order_number}` : "not verified"}</dd>
      </dl>
      <section>
        <h3 className="font-bold">Guardrails</h3>
        {trace.guardrails.length === 0 ? <p className="text-muted">None recorded.</p> : null}
        <ul className="mt-1 space-y-2">
          {trace.guardrails.map((item, index) => (
            <li key={`${item.rule}-${index}`}>
              <span className="font-bold">{item.rule}</span> {item.decision}
              <span className="block text-muted">{item.detail}</span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h3 className="font-bold">Retrieval</h3>
        {trace.retrieval.length === 0 ? <p className="text-muted">No chunks retrieved.</p> : null}
        <ul className="mt-1 space-y-2">
          {trace.retrieval.map((hit) => (
            <li key={`${hit.article_id}-${hit.section}`}>
              <span className="font-bold">{hit.title}</span> § {hit.section}
              <span className="block tabular-nums text-muted">cosine {hit.cosine} · rerank {hit.rerank}</span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h3 className="font-bold">Tools</h3>
        {trace.tools.length === 0 ? <p className="text-muted">No tool call.</p> : null}
        {trace.tools.map((tool, index) => (
          <div key={`${tool.name}-${index}`} className="mt-2">
            <p className="font-bold">
              {tool.name} {tool.ok ? "ok" : "denied"}
            </p>
            <pre className="mt-1 overflow-auto rounded-lg bg-canvas p-2 font-mono text-xs leading-5">{JSON.stringify({ arguments: tool.arguments, result: tool.result }, null, 2)}</pre>
          </div>
        ))}
      </section>
    </div>
  );
}

function labelStatus(status: string) {
  if (status === "handed_off") return "Handed off";
  if (status === "resolved") return "Resolved";
  return "Open";
}
