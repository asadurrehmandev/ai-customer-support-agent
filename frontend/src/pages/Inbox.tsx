import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getInbox, handleTicket, when, type Ticket } from "../api.ts";

export function Inbox() {
  const [rows, setRows] = useState<Ticket[] | null>(null);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  async function load() {
    try {
      setRows(await getInbox());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the inbox.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const selected = rows?.find((row) => row.id === openId) || null;
  const waiting = (rows || []).filter((row) => row.status !== "handled");

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-5xl px-4 py-6 pb-24">
        <h1 className="text-2xl font-bold">Inbox</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Handoffs land here with the transcript, a template summary, the intent, the sentiment, and any action already taken. Zendesk is used only when it is configured. Otherwise the ticket stays local.
        </p>
        {error ? <p className="mt-4 text-sm text-danger">{error}</p> : null}
        {rows === null && !error ? <p className="mt-4 text-sm text-muted">Loading the queue</p> : null}
        {rows && waiting.length === 0 ? <p className="mt-6 text-sm text-muted">No conversations are waiting for a person.</p> : null}
        <div className="mt-4 overflow-hidden rounded-xl border border-line">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="bg-sheet text-muted">
              <tr>
                <th className="px-3 py-2 font-bold">Reason</th>
                <th className="px-3 py-2 font-bold">Customer</th>
                <th className="hidden px-3 py-2 font-bold sm:table-cell">Sentiment</th>
                <th className="px-3 py-2 font-bold">When</th>
                <th className="hidden px-3 py-2 font-bold md:table-cell">Desk</th>
              </tr>
            </thead>
            <tbody>
              {(rows || []).map((row) => (
                <tr
                  key={row.id}
                  tabIndex={0}
                  className={`cursor-pointer border-t border-line ${openId === row.id ? "bg-yellow text-[#141816]" : ""} ${row.status === "handled" && openId !== row.id ? "text-muted" : ""}`}
                  onClick={() => setOpenId(row.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setOpenId(row.id);
                    }
                  }}
                >
                  <td className="px-3 py-2">{row.reason.replaceAll("_", " ")}</td>
                  <td className="px-3 py-2">{row.customer_name || row.customer_email || "Unverified"}</td>
                  <td className="hidden px-3 py-2 sm:table-cell">{row.sentiment}</td>
                  <td className="px-3 py-2 tabular-nums">{when(row.created_at)}</td>
                  <td className="hidden px-3 py-2 md:table-cell">{row.zendesk_id ? `Zendesk ${row.zendesk_id}` : "Local only"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {selected ? (
          <article className="mt-6 rounded-xl border border-line bg-sheet p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <h2 className="text-lg font-bold">{selected.reason.replaceAll("_", " ")}</h2>
              {selected.status !== "handled" ? (
                <button
                  type="button"
                  className="rounded-lg bg-yellow px-3 py-2 text-sm font-bold text-[#141816]"
                  onClick={() => void handleTicket(selected.id).then(load)}
                >
                  Mark handled
                </button>
              ) : (
                <p className="text-sm text-muted">Handled</p>
              )}
            </div>
            <p className="mt-3 text-sm leading-6">{selected.summary}</p>
            <p className="mt-2 text-sm text-muted">Actions: {selected.actions.length ? selected.actions.join(", ") : "none"}</p>
            <Link to={`/conversations/${selected.conversation_id}`} className="mt-3 inline-block text-sm font-bold text-ink">
              Open the conversation
            </Link>
            <h3 className="mt-4 font-bold">Transcript</h3>
            <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-canvas p-3 font-mono text-xs leading-5">{selected.transcript}</pre>
          </article>
        ) : null}
      </div>
    </div>
  );
}
