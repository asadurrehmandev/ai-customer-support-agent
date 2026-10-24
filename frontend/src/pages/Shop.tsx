import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getFixtures, money, type Fixture } from "../api.ts";
import { Mark } from "../App.tsx";
import { Empty } from "../Empty.tsx";

export function Shop() {
  const [fixtures, setFixtures] = useState<Fixture[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const script = document.createElement("script");
    script.src = "/widget/keel.js";
    script.async = false;
    script.dataset.api = window.location.origin;
    document.body.appendChild(script);
    return () => {
      script.remove();
      document.querySelector("[data-keel-widget]")?.remove();
    };
  }, []);

  useEffect(() => {
    getFixtures()
      .then(setFixtures)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load demo orders."));
  }, []);

  return (
    <div className="min-h-dvh bg-canvas text-ink">
      <header className="flex items-center justify-between border-b border-line px-4 py-4 md:px-10">
        <div className="flex items-center gap-2">
          <Mark />
          <div>
            <p className="text-lg font-bold">Marlow & Hale</p>
            <p className="text-sm text-muted">Cookware and linen · Portland, Maine</p>
          </div>
        </div>
        <Link to="/" className="text-sm font-bold text-ink">
          Agent console
        </Link>
      </header>
      <main className="mx-auto grid max-w-5xl gap-8 px-4 py-8 md:grid-cols-[minmax(0,1fr)_280px] md:px-10">
        <article>
          <Pan />
          <h1 className="mt-6 text-3xl font-bold leading-tight">10-inch carbon steel frying pan</h1>
          <p className="mt-2 text-lg tabular-nums">$84.00</p>
          <p className="mt-4 max-w-xl text-sm leading-6">
            Uncoated iron and carbon, seasoned before it leaves the Portland workshop. Wash it by hand, dry it on a low burner, and keep it out of the dishwasher. Ground shipping is $8, or free on orders of $75 or more before tax.
          </p>
          <p className="mt-4 text-sm text-muted">This is the fictional shop the widget is embedded in. The Help button opens Keel.</p>
        </article>
        <aside className="text-sm">
          <h2 className="font-bold">Care, briefly</h2>
          <ul className="mt-2 list-disc space-y-1 pl-4 text-muted">
            <li>Dry on a burner, then a thin film of oil.</li>
            <li>Warranty is 5 years for manufacturing defects.</li>
            <li>Cancel an order within 24 hours, before it ships.</li>
          </ul>
        </aside>
      </main>
      <section className="mx-auto max-w-5xl px-4 pb-24 md:px-10">
        <h2 className="text-xl font-bold">Fictional orders in this demo</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          These rows are the seeded shop, not real people. Use an order number with its email or postcode in the chat. The status is read from the database, so it changes if Keel cancels or edits the order.
        </p>
        {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}
        {fixtures === null && !error ? <p className="mt-3 text-sm text-muted">Loading orders</p> : null}
        {fixtures && fixtures.length === 0 ? (
          <div className="mt-4">
            <Empty title="No demo orders">The shop database has no orders to show. Chat can still answer help-center questions.</Empty>
          </div>
        ) : null}
        {fixtures && fixtures.length > 0 ? (
        <div className="mt-4 overflow-x-auto rounded-xl border border-line">
          <table className="w-full min-w-[640px] border-collapse text-left text-sm">
            <thead className="bg-sheet text-muted">
              <tr>
                <th className="px-3 py-2 font-bold">Order</th>
                <th className="px-3 py-2 font-bold">Email</th>
                <th className="px-3 py-2 font-bold">Postcode</th>
                <th className="px-3 py-2 font-bold">Status</th>
                <th className="px-3 py-2 font-bold">Total</th>
                <th className="px-3 py-2 font-bold">Why it's here</th>
              </tr>
            </thead>
            <tbody>
              {(fixtures || []).map((row) => (
                <tr key={row.number} className="border-t border-line">
                  <td className="px-3 py-2 font-bold">{row.number}</td>
                  <td className="px-3 py-2">{row.email}</td>
                  <td className="px-3 py-2 tabular-nums">{row.postcode}</td>
                  <td className="px-3 py-2">{row.status}</td>
                  <td className="px-3 py-2 tabular-nums">{money(row.total_cents)}</td>
                  <td className="px-3 py-2">{row.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        ) : null}
      </section>
    </div>
  );
}

function Pan() {
  return (
    <svg viewBox="0 0 640 280" className="w-full rounded-2xl bg-pine text-yellow" role="img" aria-label="Line drawing of a frying pan">
      <ellipse cx="230" cy="150" rx="150" ry="70" fill="none" stroke="currentColor" strokeWidth="3" />
      <path d="M370 150h180" stroke="currentColor" strokeWidth="10" strokeLinecap="round" />
      <path d="M120 150c20-50 200-50 220 0" fill="none" stroke="currentColor" strokeWidth="3" />
    </svg>
  );
}
