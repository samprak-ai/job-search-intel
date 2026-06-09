"use client";

import { useCallback, useEffect, useState } from "react";

import { API_BASE as API } from "@/lib/api";

// ── Types ───────────────────────────────────────────────────────────────────
type CalibrationItem = {
  role_id: string;
  status: string;
  outcome_date: string | null;
  predicted_match_tier: string | null;
  predicted_overall_score: number | null;
  title: string | null;
  company: string | null;
};

type ProposedChange = {
  kind: string;
  proposal: string;
  rationale: string;
  confidence: string;
};

type CalibrationFinding = {
  segment: string;
  direction: string;
  magnitude: string;
  evidence_count: number;
  note: string;
};

type Report = {
  data_sufficiency: string;
  headline: string;
  calibration_findings: CalibrationFinding[];
  proposed_changes: ProposedChange[];
  watch_items: string[];
  inputs_summary?: { outcomes: number; open_gaps: number };
};

type Gap = {
  id: string;
  gap_type: string;
  severity: string;
  description: string;
  role_label: string | null;
  status: string;
  source: string;
  detected_at: string;
};

type Adjustment = {
  id: string;
  scope: string;
  note: string;
  source: string;
  created_at: string;
};

// ── Helpers ─────────────────────────────────────────────────────────────────
const OUTCOME_GOOD = new Set(["interview", "offer", "applied"]);
const OUTCOME_BAD = new Set(["rejected", "ghosted"]);

function outcomeColor(status: string): string {
  if (OUTCOME_GOOD.has(status)) return "bg-green-100 text-green-800";
  if (OUTCOME_BAD.has(status)) return "bg-red-100 text-red-800";
  return "bg-yellow-100 text-yellow-800";
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="mb-8 bg-white border border-gray-200 rounded-lg p-5">
      <h2 className="text-base font-semibold text-gray-900">{title}</h2>
      {subtitle && <p className="text-sm text-gray-500 mb-3">{subtitle}</p>}
      <div className={subtitle ? "" : "mt-3"}>{children}</div>
    </section>
  );
}

// ── Page ────────────────────────────────────────────────────────────────────
export default function InsightsPage() {
  const [calibration, setCalibration] = useState<CalibrationItem[]>([]);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [adjustments, setAdjustments] = useState<Adjustment[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [running, setRunning] = useState(false);
  const [approved, setApproved] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    const [c, g, a] = await Promise.all([
      fetch(`${API}/application-outcomes/calibration`).then((r) => r.json()).catch(() => ({ items: [] })),
      fetch(`${API}/detected-gaps?status=open`).then((r) => r.json()).catch(() => ({ items: [] })),
      fetch(`${API}/scoring-adjustments`).then((r) => r.json()).catch(() => ({ items: [] })),
    ]);
    setCalibration(c.items || []);
    setGaps(g.items || []);
    setAdjustments(a.items || []);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function runReflection() {
    setRunning(true);
    try {
      const res = await fetch(`${API}/reflect`, { method: "POST" }).then((r) => r.json());
      setReport(res.report || null);
    } finally {
      setRunning(false);
    }
  }

  async function approve(change: ProposedChange, idx: number) {
    // Infer scope from the proposal: default global, but if it names a known
    // company segment we let Sam edit before sending.
    const scope = window.prompt(
      "Scope for this adjustment ('global' or a company name):",
      "global"
    );
    if (scope === null) return;
    const note = window.prompt("Calibration note to apply to scoring:", change.proposal);
    if (note === null || !note.trim()) return;
    await fetch(`${API}/scoring-adjustments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope: scope.trim() || "global", note: note.trim(), source: "reflection" }),
    });
    setApproved((prev) => new Set(prev).add(`${idx}`));
    await load();
  }

  async function deactivate(id: string) {
    await fetch(`${API}/scoring-adjustments/${id}`, { method: "DELETE" });
    await load();
  }

  const matched = calibration.filter(
    (c) =>
      (c.predicted_overall_score ?? 0) >= 70 && OUTCOME_GOOD.has(c.status)
  ).length;

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Insights & Loop</h1>
          <p className="text-sm text-gray-500">Predicted vs. actual, reflection proposals, and active calibration.</p>
        </div>
        <button
          onClick={runReflection}
          disabled={running}
          className="text-sm px-4 py-2 bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50"
        >
          {running ? "Reflecting…" : "Run reflection"}
        </button>
      </div>

      {/* Calibration: predicted vs actual */}
      <Section
        title="Calibration — predicted vs. actual"
        subtitle={`${calibration.length} logged outcome${calibration.length === 1 ? "" : "s"}${
          calibration.length ? ` · ${matched} high-prediction roles converted (applied/interview/offer)` : ""
        }`}
      >
        {calibration.length === 0 ? (
          <p className="text-sm text-gray-400">No outcomes logged yet. Set a status on a role to start feeding the loop.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="py-2">Role</th>
                <th>Company</th>
                <th>Predicted</th>
                <th>Actual</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {calibration.map((c) => (
                <tr key={c.role_id} className="border-b last:border-0">
                  <td className="py-2 pr-2">{c.title || c.role_id.slice(0, 8)}</td>
                  <td className="pr-2 text-gray-600">{c.company}</td>
                  <td className="pr-2">
                    {c.predicted_match_tier ? `${c.predicted_match_tier} (${c.predicted_overall_score})` : "—"}
                  </td>
                  <td className="pr-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${outcomeColor(c.status)}`}>{c.status}</span>
                  </td>
                  <td className="text-gray-500">{c.outcome_date || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      {/* Reflection report + approve */}
      <Section title="Reflection" subtitle="Run the pass, then approve a proposal to apply it to future scoring.">
        {!report ? (
          <p className="text-sm text-gray-400">Click “Run reflection” to analyze outcomes + open gaps.</p>
        ) : (
          <div className="space-y-4">
            <p className="text-sm font-medium text-gray-900">
              {report.headline}{" "}
              <span className="text-gray-400 font-normal">({report.data_sufficiency} data)</span>
            </p>
            {report.calibration_findings.length > 0 && (
              <div>
                <h3 className="text-xs uppercase tracking-wide text-gray-500 mb-1">Calibration findings</h3>
                <ul className="text-sm text-gray-700 list-disc pl-5">
                  {report.calibration_findings.map((f, i) => (
                    <li key={i}>
                      <b>{f.segment}</b>: {f.direction} by {f.magnitude} ({f.evidence_count} outcomes) — {f.note}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <h3 className="text-xs uppercase tracking-wide text-gray-500 mb-1">Proposed changes</h3>
              {report.proposed_changes.length === 0 ? (
                <p className="text-sm text-gray-400">No proposals.</p>
              ) : (
                <ul className="space-y-2">
                  {report.proposed_changes.map((c, i) => (
                    <li key={i} className="border border-gray-200 rounded p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <span className="text-xs text-gray-500">[{c.kind} · {c.confidence}]</span>
                          <p className="text-sm font-medium text-gray-900">{c.proposal}</p>
                          <p className="text-xs text-gray-500">{c.rationale}</p>
                        </div>
                        <button
                          onClick={() => approve(c, i)}
                          disabled={approved.has(`${i}`)}
                          className="shrink-0 text-xs px-3 py-1.5 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
                        >
                          {approved.has(`${i}`) ? "Approved" : "Approve"}
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </Section>

      {/* Active scoring adjustments */}
      <Section title="Active calibration adjustments" subtitle="Approved notes currently shaping scores. Deactivate to stop applying one.">
        {adjustments.length === 0 ? (
          <p className="text-sm text-gray-400">None active.</p>
        ) : (
          <ul className="space-y-2">
            {adjustments.map((a) => (
              <li key={a.id} className="flex items-start justify-between gap-3 text-sm border-b last:border-0 py-2">
                <span>
                  <span className="px-2 py-0.5 rounded text-xs bg-violet-100 text-violet-800 mr-2">{a.scope}</span>
                  {a.note}
                </span>
                <button onClick={() => deactivate(a.id)} className="shrink-0 text-xs text-red-600 hover:underline">
                  Deactivate
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {/* Open detected gaps */}
      <Section title="Open gaps" subtitle="Runtime gaps the system flagged about itself.">
        {gaps.length === 0 ? (
          <p className="text-sm text-gray-400">No open gaps.</p>
        ) : (
          <ul className="space-y-2">
            {gaps.map((g) => (
              <li key={g.id} className="text-sm border-b last:border-0 py-2">
                <span className="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700 mr-2">{g.gap_type}</span>
                <span className="text-gray-400 text-xs mr-2">{g.severity}</span>
                {g.description}
                {g.role_label && <span className="text-gray-400"> — {g.role_label}</span>}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
