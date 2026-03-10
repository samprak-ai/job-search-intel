"use client";

import Link from "next/link";
import { useEffect, useState, useMemo } from "react";

import { API_BASE as API } from "@/lib/api";

type Role = {
  id: string;
  company: string;
  title: string;
  url: string;
  source: string;
  department: string | null;
  date_found: string;
  match_tier: string | null;
  overall_score: number | null;
  application_status: string | null;
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TIER_ORDER = [
  "Perfect Match",
  "Strong Match",
  "Good Match",
  "Possible Match",
  "Unlikely Match",
];

// Map old tier names (from pre-rename scoring) to new tier names
const TIER_NORMALIZE: Record<string, string> = {
  "Perfect Match": "Perfect Match",
  "Strong Match": "Strong Match",
  "Good Match": "Good Match",
  "Possible Match": "Possible Match",
  "Unlikely Match": "Unlikely Match",
  // Old tier names
  "Strong": "Strong Match",
  "Worth Applying": "Good Match",
  "Stretch": "Possible Match",
  "Skip": "Unlikely Match",
};

function normalizeTier(tier: string | null): string {
  if (!tier) return "Unscored";
  return TIER_NORMALIZE[tier] || tier;
}

const tierColor: Record<string, string> = {
  "Perfect Match": "bg-emerald-100 text-emerald-800 border-emerald-400",
  "Strong Match": "bg-green-100 text-green-800 border-green-400",
  "Good Match": "bg-blue-100 text-blue-800 border-blue-400",
  "Possible Match": "bg-yellow-100 text-yellow-800 border-yellow-400",
  "Unlikely Match": "bg-gray-100 text-gray-600 border-gray-300",
};

const tierAccent: Record<string, string> = {
  "Perfect Match": "border-l-emerald-500",
  "Strong Match": "border-l-green-500",
  "Good Match": "border-l-blue-500",
  "Possible Match": "border-l-yellow-500",
  "Unlikely Match": "border-l-gray-400",
};

const statusColor: Record<string, string> = {
  unreviewed: "bg-gray-100 text-gray-600",
  applied: "bg-blue-100 text-blue-800",
  interviewing: "bg-purple-100 text-purple-800",
  offer: "bg-green-100 text-green-800",
  rejected: "bg-red-100 text-red-800",
  skipped: "bg-yellow-100 text-yellow-800",
};

const statusOptions = [
  "unreviewed",
  "applied",
  "interviewing",
  "offer",
  "rejected",
  "skipped",
];

// ---------------------------------------------------------------------------
// Function type derivation
// ---------------------------------------------------------------------------

function getFunctionType(title: string, department: string): string {
  const dept = (department || "").toLowerCase();
  const t = title.toLowerCase();

  if (dept.includes("solutions") || t.includes("solutions architect") || t.includes("solutions engineer"))
    return "Solutions Architecture";
  if (dept.includes("go-to-market") || dept.includes("gtm") || t.includes("gtm") || t.includes("go-to-market") || t.includes("go to market"))
    return "GTM & Strategy";
  if (t.includes("partner") || t.includes("partnerships") || t.includes("business development"))
    return "Partnerships & BD";
  if (t.includes("account executive") || t.includes("sales engineer") || t.includes("sales intelligence") || t.includes("sales architect"))
    return "Sales";
  if (t.includes("product manager") || t.includes("product lead") || t.includes("product marketing") || t.includes("product owner"))
    return "Product";
  if (t.includes("applied ai") || t.includes("forward deployed") || t.includes("evangelist") || t.includes("customer engineer"))
    return "Applied AI";
  if (t.includes("customer success"))
    return "Customer Success";
  if (t.includes("head of") || t.includes("director"))
    return "Leadership";
  if (dept.includes("strategy") || t.includes("strategy & operations") || t.includes("strategic"))
    return "Strategy & Ops";
  return "Other";
}

// ---------------------------------------------------------------------------
// Grouping logic
// ---------------------------------------------------------------------------

type GroupedData = {
  tier: string;
  count: number;
  companies: {
    company: string;
    count: number;
    functions: {
      functionType: string;
      count: number;
      roles: Role[];
    }[];
  }[];
}[];

function groupRoles(roles: Role[]): GroupedData {
  // Group into: tier → company → functionType → roles
  const tierMap = new Map<
    string,
    Map<string, Map<string, Role[]>>
  >();

  for (const role of roles) {
    const tier = normalizeTier(role.match_tier);
    const company = role.company;
    const fnType = getFunctionType(role.title, role.department || "");

    if (!tierMap.has(tier)) tierMap.set(tier, new Map());
    const companyMap = tierMap.get(tier)!;

    if (!companyMap.has(company)) companyMap.set(company, new Map());
    const fnMap = companyMap.get(company)!;

    if (!fnMap.has(fnType)) fnMap.set(fnType, []);
    fnMap.get(fnType)!.push(role);
  }

  // Convert to sorted arrays
  const result: GroupedData = [];

  for (const tier of TIER_ORDER) {
    const companyMap = tierMap.get(tier);
    if (!companyMap) continue;

    let tierCount = 0;
    const companies: GroupedData[number]["companies"] = [];

    // Sort companies alphabetically
    const sortedCompanies = [...companyMap.keys()].sort();
    for (const company of sortedCompanies) {
      const fnMap = companyMap.get(company)!;
      let companyCount = 0;
      const functions: GroupedData[number]["companies"][number]["functions"] = [];

      // Sort function types alphabetically
      const sortedFns = [...fnMap.keys()].sort();
      for (const fnType of sortedFns) {
        const fnRoles = fnMap.get(fnType)!;
        // Sort roles by score descending
        fnRoles.sort((a, b) => (b.overall_score || 0) - (a.overall_score || 0));
        companyCount += fnRoles.length;
        functions.push({ functionType: fnType, count: fnRoles.length, roles: fnRoles });
      }

      tierCount += companyCount;
      companies.push({ company, count: companyCount, functions });
    }

    result.push({ tier, count: tierCount, companies });
  }

  // Handle "Unscored" tier if any
  const unscoredMap = tierMap.get("Unscored");
  if (unscoredMap) {
    let tierCount = 0;
    const companies: GroupedData[number]["companies"] = [];
    const sortedCompanies = [...unscoredMap.keys()].sort();
    for (const company of sortedCompanies) {
      const fnMap = unscoredMap.get(company)!;
      let companyCount = 0;
      const functions: GroupedData[number]["companies"][number]["functions"] = [];
      const sortedFns = [...fnMap.keys()].sort();
      for (const fnType of sortedFns) {
        const fnRoles = fnMap.get(fnType)!;
        companyCount += fnRoles.length;
        functions.push({ functionType: fnType, count: fnRoles.length, roles: fnRoles });
      }
      tierCount += companyCount;
      companies.push({ company, count: companyCount, functions });
    }
    result.push({ tier: "Unscored", count: tierCount, companies });
  }

  return result;
}

// ---------------------------------------------------------------------------
// Chevron icon
// ---------------------------------------------------------------------------

function Chevron({ expanded }: { expanded: boolean }) {
  return (
    <svg
      className={`w-4 h-4 transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterCompany, setFilterCompany] = useState("");
  const [filterTier, setFilterTier] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [scoringId, setScoringId] = useState<string | null>(null);
  const [updatingStatusId, setUpdatingStatusId] = useState<string | null>(null);

  // Action states
  const [batchGenerating, setBatchGenerating] = useState(false);
  const [batchResult, setBatchResult] = useState<string | null>(null);
  const [batchScoring, setBatchScoring] = useState(false);
  const [batchScoreResult, setBatchScoreResult] = useState<string | null>(null);
  const [discoveringCompany, setDiscoveringCompany] = useState<string | null>(null);
  const [discoveryResult, setDiscoveryResult] = useState<string | null>(null);

  // Usage tracking
  const [usageStats, setUsageStats] = useState<{
    total_queries: number;
    by_provider: { serper: number; brave: number };
    daily: { date: string; total: number; serper: number; brave: number }[];
  } | null>(null);

  // Accordion state
  const [expandedTiers, setExpandedTiers] = useState<Set<string>>(new Set());
  const [expandedCompanies, setExpandedCompanies] = useState<Set<string>>(new Set());
  const [expandedFunctions, setExpandedFunctions] = useState<Set<string>>(new Set());

  useEffect(() => {
    fetchRoles();
    fetchUsage();
  }, []);

  async function fetchRoles() {
    setLoading(true);
    const res = await fetch(`${API}/roles?limit=500`);
    const data = await res.json();
    setRoles(data.roles);
    setLoading(false);
  }

  async function fetchUsage() {
    try {
      const res = await fetch(`${API}/usage?days=7`);
      const data = await res.json();
      setUsageStats(data);
    } catch (e) {
      console.error("Usage fetch failed:", e);
    }
  }

  async function scoreRole(roleId: string) {
    setScoringId(roleId);
    try {
      await fetch(`${API}/score/${roleId}`, { method: "POST" });
      await fetchRoles();
    } catch (e) {
      console.error("Scoring failed:", e);
    }
    setScoringId(null);
  }

  async function updateStatus(roleId: string, status: string) {
    setUpdatingStatusId(roleId);
    try {
      await fetch(`${API}/roles/${roleId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ application_status: status }),
      });
      setRoles((prev) =>
        prev.map((r) =>
          r.id === roleId ? { ...r, application_status: status } : r
        )
      );
    } catch (e) {
      console.error("Status update failed:", e);
    }
    setUpdatingStatusId(null);
  }

  async function batchGeneratePrep() {
    setBatchGenerating(true);
    setBatchResult(null);
    try {
      const res = await fetch(`${API}/forge/session/batch`, { method: "POST" });
      const data = await res.json();
      setBatchResult(
        `Generated ${data.generated} prep briefs (${data.skipped} already existed, ${data.failed} failed)`
      );
    } catch (e) {
      console.error("Batch generation failed:", e);
      setBatchResult("Batch generation failed");
    }
    setBatchGenerating(false);
  }

  async function discoverCompany(companyName: string) {
    setDiscoveringCompany(companyName);
    setDiscoveryResult(null);
    try {
      const res = await fetch(`${API}/discover/${encodeURIComponent(companyName)}`, {
        method: "POST",
      });
      const data = await res.json();
      setDiscoveryResult(
        `${companyName}: ${data.new_roles} new roles found (${data.scored || 0} scored)`
      );
      await fetchRoles();
    } catch (e) {
      console.error(`Discovery failed for ${companyName}:`, e);
      setDiscoveryResult(`Discovery failed for ${companyName}`);
    }
    setDiscoveringCompany(null);
  }

  async function batchScoreAll() {
    setBatchScoring(true);
    setBatchScoreResult(null);
    try {
      const res = await fetch(`${API}/score/batch`, { method: "POST" });
      const data = await res.json();
      setBatchScoreResult(
        `Scored ${data.scored} roles (${data.failed} failed, ${data.total_unscored} were unscored)`
      );
      await fetchRoles();
    } catch (e) {
      console.error("Batch scoring failed:", e);
      setBatchScoreResult("Batch scoring failed");
    }
    setBatchScoring(false);
  }

  // Toggle helpers
  function toggleTier(tier: string) {
    setExpandedTiers((prev) => {
      const next = new Set(prev);
      if (next.has(tier)) next.delete(tier);
      else next.add(tier);
      return next;
    });
  }

  function toggleCompany(key: string) {
    setExpandedCompanies((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleFunction(key: string) {
    setExpandedFunctions((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  // Filters
  const companies = [...new Set(roles.map((r) => r.company))].sort();
  const filtered = roles.filter((r) => {
    if (filterCompany && r.company !== filterCompany) return false;
    const normalized = normalizeTier(r.match_tier);
    if (filterTier === "unscored" && normalized !== "Unscored") return false;
    if (filterTier && filterTier !== "unscored" && normalized !== filterTier)
      return false;
    if (filterStatus && (r.application_status || "unreviewed") !== filterStatus)
      return false;
    return true;
  });

  // Group filtered roles into cascaded structure
  const grouped = useMemo(() => groupRoles(filtered), [filtered]);

  return (
    <main className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Discovered Roles</h1>
        <span className="text-sm text-gray-500">
          {filtered.length} of {roles.length} roles
        </span>
      </div>

      {/* Action bar */}
      <div className="flex flex-wrap items-center gap-3 mb-4 p-4 bg-white rounded-lg border border-gray-200">
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wider mr-1">Actions</span>

        {/* Batch prep brief generation */}
        <button
          onClick={batchGeneratePrep}
          disabled={batchGenerating}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {batchGenerating ? (
            <>
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Generating...
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
              Generate All Prep Briefs
            </>
          )}
        </button>

        {/* Batch score unscored */}
        <button
          onClick={batchScoreAll}
          disabled={batchScoring}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {batchScoring ? (
            <>
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Scoring...
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Score All Unscored
            </>
          )}
        </button>

        <div className="h-6 w-px bg-gray-200" />

        {/* Company discovery buttons */}
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wider mr-1">Discover</span>
        {["Anthropic", "OpenAI", "xAI", "Google DeepMind"].map((company) => (
          <button
            key={company}
            onClick={() => discoverCompany(company)}
            disabled={discoveringCompany !== null}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {discoveringCompany === company ? (
              <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            )}
            {company}
          </button>
        ))}
      </div>

      {/* Status messages */}
      {(batchResult || batchScoreResult || discoveryResult) && (
        <div className="mb-4 space-y-2">
          {batchResult && (
            <div className="p-3 text-sm rounded-lg bg-indigo-50 text-indigo-800 border border-indigo-200 flex items-center justify-between">
              <span>{batchResult}</span>
              <button onClick={() => setBatchResult(null)} className="text-indigo-400 hover:text-indigo-600 ml-2">&times;</button>
            </div>
          )}
          {batchScoreResult && (
            <div className="p-3 text-sm rounded-lg bg-green-50 text-green-800 border border-green-200 flex items-center justify-between">
              <span>{batchScoreResult}</span>
              <button onClick={() => setBatchScoreResult(null)} className="text-green-400 hover:text-green-600 ml-2">&times;</button>
            </div>
          )}
          {discoveryResult && (
            <div className="p-3 text-sm rounded-lg bg-emerald-50 text-emerald-800 border border-emerald-200 flex items-center justify-between">
              <span>{discoveryResult}</span>
              <button onClick={() => setDiscoveryResult(null)} className="text-emerald-400 hover:text-emerald-600 ml-2">&times;</button>
            </div>
          )}
        </div>
      )}

      {/* API Usage widget */}
      {usageStats && (
        <div className="mb-4 p-4 bg-white rounded-lg border border-gray-200">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
              </svg>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">API Usage (7 days)</span>
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span>Total: <strong className="text-gray-700">{usageStats.total_queries}</strong></span>
              {usageStats.by_provider.serper > 0 && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-50 text-blue-700">
                  Serper: {usageStats.by_provider.serper}
                </span>
              )}
              {usageStats.by_provider.brave > 0 && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-orange-50 text-orange-700">
                  Brave: {usageStats.by_provider.brave}
                </span>
              )}
            </div>
          </div>

          {/* Mini bar chart */}
          {usageStats.daily.length > 0 && (
            <div className="flex items-end gap-1 h-12">
              {usageStats.daily.map((day) => {
                const maxTotal = Math.max(...usageStats.daily.map((d) => d.total), 1);
                const heightPct = Math.max((day.total / maxTotal) * 100, 4);
                return (
                  <div key={day.date} className="flex-1 flex flex-col items-center gap-0.5" title={`${day.date}: ${day.total} queries`}>
                    <div className="w-full flex flex-col justify-end" style={{ height: "36px" }}>
                      {day.serper > 0 && (
                        <div
                          className="w-full bg-blue-400 rounded-t-sm"
                          style={{ height: `${(day.serper / maxTotal) * 36}px`, minHeight: day.serper > 0 ? "2px" : "0" }}
                        />
                      )}
                      {day.brave > 0 && (
                        <div
                          className="w-full bg-orange-400 rounded-b-sm"
                          style={{ height: `${(day.brave / maxTotal) * 36}px`, minHeight: day.brave > 0 ? "2px" : "0" }}
                        />
                      )}
                    </div>
                    <span className="text-[9px] text-gray-400">{day.date.slice(5)}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Filter bar */}
      <div className="flex gap-3 mb-6">
        <select
          value={filterCompany}
          onChange={(e) => setFilterCompany(e.target.value)}
          className="text-sm border border-gray-300 rounded px-3 py-1.5 bg-white"
        >
          <option value="">All Companies</option>
          {companies.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          value={filterTier}
          onChange={(e) => setFilterTier(e.target.value)}
          className="text-sm border border-gray-300 rounded px-3 py-1.5 bg-white"
        >
          <option value="">All Tiers</option>
          <option value="Perfect Match">Perfect Match</option>
          <option value="Strong Match">Strong Match</option>
          <option value="Good Match">Good Match</option>
          <option value="Possible Match">Possible Match</option>
          <option value="Unlikely Match">Unlikely Match</option>
          <option value="unscored">Unscored</option>
        </select>
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="text-sm border border-gray-300 rounded px-3 py-1.5 bg-white"
        >
          <option value="">All Statuses</option>
          {statusOptions.map((s) => (
            <option key={s} value={s}>
              {s.charAt(0).toUpperCase() + s.slice(1)}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <p className="text-gray-500">Loading roles...</p>
      ) : grouped.length === 0 ? (
        <p className="text-gray-500">No roles match the current filters.</p>
      ) : (
        <div className="space-y-2">
          {grouped.map(({ tier, count, companies: tierCompanies }) => {
            const tierExpanded = expandedTiers.has(tier);
            const accent = tierAccent[tier] || "border-l-gray-400";
            const badgeColor = tierColor[tier] || "bg-gray-100 text-gray-600 border-gray-300";

            return (
              <div key={tier} className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                {/* ── Level 1: Match Tier ── */}
                <button
                  onClick={() => toggleTier(tier)}
                  className={`w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors border-l-4 ${accent}`}
                >
                  <Chevron expanded={tierExpanded} />
                  <span className={`inline-flex items-center px-2.5 py-0.5 rounded text-xs font-semibold border ${badgeColor}`}>
                    {tier}
                  </span>
                  <span className="text-sm font-medium text-gray-700">
                    {count} {count === 1 ? "role" : "roles"}
                  </span>
                </button>

                {tierExpanded && (
                  <div className="border-t border-gray-100">
                    {tierCompanies.map(({ company, count: companyCount, functions }) => {
                      const companyKey = `${tier}:${company}`;
                      const companyExpanded = expandedCompanies.has(companyKey);

                      return (
                        <div key={companyKey}>
                          {/* ── Level 2: Company ── */}
                          <button
                            onClick={() => toggleCompany(companyKey)}
                            className="w-full flex items-center gap-3 pl-10 pr-4 py-2.5 hover:bg-gray-50 transition-colors border-t border-gray-50"
                          >
                            <Chevron expanded={companyExpanded} />
                            <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21" />
                            </svg>
                            <span className="text-sm font-medium text-gray-800">{company}</span>
                            <span className="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
                              {companyCount}
                            </span>
                          </button>

                          {companyExpanded && (
                            <div>
                              {functions.map(({ functionType, count: fnCount, roles: fnRoles }) => {
                                const fnKey = `${tier}:${company}:${functionType}`;
                                const fnExpanded = expandedFunctions.has(fnKey);

                                return (
                                  <div key={fnKey}>
                                    {/* ── Level 3: Function Type ── */}
                                    <button
                                      onClick={() => toggleFunction(fnKey)}
                                      className="w-full flex items-center gap-3 pl-16 pr-4 py-2 hover:bg-gray-50 transition-colors"
                                    >
                                      <Chevron expanded={fnExpanded} />
                                      <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                                        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
                                      </svg>
                                      <span className="text-sm text-gray-700">{functionType}</span>
                                      <span className="text-xs text-gray-400 bg-gray-50 px-2 py-0.5 rounded-full">
                                        {fnCount}
                                      </span>
                                    </button>

                                    {fnExpanded && (
                                      <div className="bg-gray-50/50">
                                        {/* Role header */}
                                        <div className="flex items-center pl-24 pr-4 py-1.5 text-xs font-medium text-gray-400 uppercase tracking-wider border-b border-gray-100">
                                          <span className="flex-1">Title</span>
                                          <span className="w-16 text-center">Score</span>
                                          <span className="w-32 text-center">Status</span>
                                          <span className="w-20 text-right">Actions</span>
                                        </div>

                                        {/* ── Level 4: Individual roles ── */}
                                        {fnRoles.map((role) => {
                                          const currentStatus = role.application_status || "unreviewed";
                                          return (
                                            <div
                                              key={role.id}
                                              className="flex items-center pl-24 pr-4 py-2 hover:bg-white transition-colors border-b border-gray-100 last:border-b-0"
                                            >
                                              <div className="flex-1 min-w-0">
                                                <Link
                                                  href={`/role/${role.id}`}
                                                  className="text-sm text-blue-600 hover:text-blue-800 hover:underline truncate block"
                                                  title={role.title}
                                                >
                                                  {role.title}
                                                </Link>
                                              </div>
                                              <div className="w-16 text-center">
                                                <span className="text-sm text-gray-600 font-medium">
                                                  {role.overall_score ?? "—"}
                                                </span>
                                              </div>
                                              <div className="w-32 text-center">
                                                <select
                                                  value={currentStatus}
                                                  onChange={(e) =>
                                                    updateStatus(role.id, e.target.value)
                                                  }
                                                  disabled={updatingStatusId === role.id}
                                                  className={`text-xs px-2 py-1 rounded border-0 font-medium cursor-pointer ${statusColor[currentStatus] || "bg-gray-100"}`}
                                                >
                                                  {statusOptions.map((s) => (
                                                    <option key={s} value={s}>
                                                      {s.charAt(0).toUpperCase() + s.slice(1)}
                                                    </option>
                                                  ))}
                                                </select>
                                              </div>
                                              <div className="w-20 text-right">
                                                {!role.match_tier && (
                                                  <button
                                                    onClick={() => scoreRole(role.id)}
                                                    disabled={scoringId === role.id}
                                                    className="text-xs px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                                                  >
                                                    {scoringId === role.id ? "..." : "Score"}
                                                  </button>
                                                )}
                                              </div>
                                            </div>
                                          );
                                        })}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
