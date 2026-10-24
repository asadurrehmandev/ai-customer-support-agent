import { useEffect, useState } from "react";
import { getMetrics, type Metrics as MetricsBody } from "../api.ts";
import { Empty } from "../Empty.tsx";

export function Metrics() {
  const [data, setData] = useState<MetricsBody | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getMetrics()
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Could not load metrics."));
  }, []);

  const reasons = Object.entries(data?.handoff_reasons || {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-3xl px-4 py-6 pb-24">
        <h1 className="text-2xl font-bold">Metrics</h1>
        <p className="mt-2 text-sm leading-6 text-muted">
          Every figure on this page is counted from conversations stored in this database. Nothing here is a benchmark or a sample pasted in by hand.
        </p>
        {error ? <p className="mt-4 text-sm text-danger">{error}</p> : null}
        {data === null && !error ? <p className="mt-4 text-sm text-muted">Loading metrics</p> : null}
        {data && data.conversations === 0 ? (
          <div className="mt-6">
            <Empty title="No conversations stored">Deflection and CSAT are counted from rows in this database. There are none yet, so those rates are not computed.</Empty>
          </div>
        ) : null}
        {data && data.conversations > 0 ? (
          <>
            <table className="mt-6 w-full border-collapse text-sm">
              <caption className="mb-2 text-left font-bold">Deflection</caption>
              <thead>
                <tr className="border-b border-line text-left text-muted">
                  <th className="py-2 font-bold">Figure</th>
                  <th className="py-2 text-right font-bold">Count</th>
                </tr>
              </thead>
              <tbody>
                <Row label="Conversations" value={String(data.conversations)} />
                <Row label="Open, excluded from the rate" value={String(data.open)} />
                <Row label="Closed" value={String(data.closed)} />
                <Row label="Resolved without a handoff" value={String(data.deflected)} />
                <Row label="Handed off" value={String(data.handed_off)} />
                <Row label="Deflection rate" value={rate(data.deflection_rate, data.deflected, data.closed)} />
              </tbody>
            </table>
            <p className="mt-3 text-sm leading-6 text-muted">{data.definition}</p>
            <h2 className="mt-8 text-lg font-bold">Handoff reasons</h2>
            {reasons.length === 0 ? <p className="mt-2 text-sm text-muted">No handoff tickets yet.</p> : null}
            <table className="mt-2 w-full border-collapse text-sm">
              <tbody>
                {reasons.map(([reason, count]) => (
                  <tr key={reason} className="border-t border-line">
                    <td className="py-2">{reason.replaceAll("_", " ")}</td>
                    <td className="py-2 text-right tabular-nums">{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h2 className="mt-8 text-lg font-bold">CSAT</h2>
            <table className="mt-2 w-full border-collapse text-sm">
              <tbody>
                <Row label="Thumbs up" value={String(data.csat_up)} />
                <Row label="Thumbs down" value={String(data.csat_down)} />
                <Row label="Rate" value={data.csat_total === 0 ? "Not computed. No votes yet." : `${data.csat_up} of ${data.csat_total}`} />
              </tbody>
            </table>
            <h2 className="mt-8 text-lg font-bold">Outcomes</h2>
            <table className="mt-2 w-full border-collapse text-sm">
              <tbody>
                {Object.entries(data.outcomes).map(([name, count]) => (
                  <Row key={name} label={name} value={String(count)} />
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <tr className="border-t border-line">
      <td className="py-2">{label}</td>
      <td className="py-2 text-right tabular-nums">{value}</td>
    </tr>
  );
}

function rate(value: number | null, numerator: number, denominator: number) {
  if (value === null || denominator === 0) return "Not computed. No closed conversations yet.";
  return `${numerator} of ${denominator} (${Math.round(value * 1000) / 10}%)`;
}
