"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { API_BASE as API } from "@/lib/api";

const tierColor: Record<string, string> = {
  "Perfect Match": "bg-emerald-100 text-emerald-800 border-emerald-200",
  "Strong Match": "bg-green-100 text-green-800 border-green-200",
  "Good Match": "bg-blue-100 text-blue-800 border-blue-200",
  "Possible Match": "bg-yellow-100 text-yellow-800 border-yellow-200",
  "Unlikely Match": "bg-gray-100 text-gray-600 border-gray-200",
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

type Score = {
  match_tier: string;
  overall_score: number;
  dimension_scores: Record<string, number>;
  rationale: string;
  gaps: string[];
  cover_letter_angles: string[];
};

type Intel = {
  role_type: string;
  interview_structure: string;
  question_themes: string[];
  emphasis_areas: string[];
  culture_signals: string[];
};

type QuestionTheme = {
  theme: string;
  likely_question: string;
  leverage_from_resume: string;
  directional_angle: string;
};

type ResumeLeverage = {
  experience: string;
  why_it_maps: string;
};

type GapMitigation = {
  gap: string;
  strategy: string;
};

type SessionConfig = {
  company_interview_philosophy: string;
  question_themes: QuestionTheme[];
  resume_leverage_map: ResumeLeverage[];
  gap_mitigation: GapMitigation[];
  opening_pitch: string;
};

type Session = {
  id: string;
  role_id: string;
  session_config: SessionConfig;
  created_at: string;
};

type RoleData = {
  id: string;
  company: string;
  title: string;
  url: string;
  source: string;
  raw_jd: string;
  date_found: string;
  application_status: string | null;
  score: Score | null;
  interview_intel: Intel[];
  session: Session | null;
};

export default function RoleDetail() {
  const params = useParams();
  const id = params.id as string;
  const [role, setRole] = useState<RoleData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scoring, setScoring] = useState(false);
  const [fetchingIntel, setFetchingIntel] = useState(false);
  const [generatingSession, setGeneratingSession] = useState(false);

  useEffect(() => {
    fetchRole();
  }, [id]);

  async function fetchRole() {
    setLoading(true);
    const res = await fetch(`${API}/roles/${id}`);
    const data = await res.json();
    setRole(data);
    setLoading(false);
  }

  async function scoreRole() {
    setScoring(true);
    await fetch(`${API}/score/${id}`, { method: "POST" });
    await fetchRole();
    setScoring(false);
  }

  async function fetchIntel() {
    if (!role) return;
    setFetchingIntel(true);
    await fetch(
      `${API}/intel/${encodeURIComponent(role.company)}?role_type=AI+Solutions+Engineer`,
      { method: "POST" }
    );
    await fetchRole();
    setFetchingIntel(false);
  }

  async function updateStatus(status: string) {
    if (!role) return;
    await fetch(`${API}/roles/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ application_status: status }),
    });
    setRole({ ...role, application_status: status });
  }

  async function generateForgeSession() {
    setGeneratingSession(true);
    try {
      await fetch(`${API}/forge/session/${id}`, { method: "POST" });
      await fetchRole();
    } catch (e) {
      console.error("Forge session generation failed:", e);
    }
    setGeneratingSession(false);
  }

  if (loading) return <main className="p-8 text-gray-500">Loading...</main>;
  if (!role) return <main className="p-8 text-red-500">Role not found</main>;

  const score = role.score;
  const intel = role.interview_intel;
  const session = role.session;
  const currentStatus = role.application_status || "unreviewed";

  return (
    <main className="p-6">
      <Link
        href="/dashboard"
        className="text-sm text-blue-600 hover:underline mb-4 inline-block"
      >
        &larr; Back to Dashboard
      </Link>

      <div className="mb-6">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h1 className="text-2xl font-bold">{role.title}</h1>
              <select
                value={currentStatus}
                onChange={(e) => updateStatus(e.target.value)}
                className={`text-xs px-2 py-1 rounded border-0 font-medium cursor-pointer ${statusColor[currentStatus] || "bg-gray-100"}`}
              >
                {statusOptions.map((s) => (
                  <option key={s} value={s}>
                    {s.charAt(0).toUpperCase() + s.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            <p className="text-gray-500">
              {role.company} &middot; {role.source} &middot;{" "}
              {new Date(role.date_found).toLocaleDateString()}
            </p>
          </div>
          <a
            href={role.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm px-3 py-1.5 bg-gray-100 text-gray-700 rounded hover:bg-gray-200"
          >
            View Original
          </a>
        </div>
      </div>

      {/* Job Description */}
      <section className="bg-white rounded-lg border border-gray-200 p-5 mb-6">
        <h2 className="font-semibold mb-3">Job Description</h2>
        {role.raw_jd ? (
          <div
            className="text-sm text-gray-700 prose prose-sm max-w-none
              prose-headings:text-gray-800 prose-headings:font-semibold prose-headings:mt-4 prose-headings:mb-2
              prose-p:my-2 prose-ul:my-2 prose-li:my-0.5
              prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline"
            dangerouslySetInnerHTML={{ __html: role.raw_jd }}
          />
        ) : (
          <p className="text-sm text-gray-400">No description available</p>
        )}
      </section>

      {/* Match Score */}
      <section className="bg-white rounded-lg border border-gray-200 p-5 mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Match Score</h2>
          <button
            onClick={scoreRole}
            disabled={scoring}
            className="text-xs px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {scoring ? "Scoring..." : score ? "Re-Score" : "Score This Role"}
          </button>
        </div>

        {score ? (
          <div>
            <div className="flex items-center gap-3 mb-4">
              <span
                className={`px-3 py-1 rounded text-sm font-medium ${tierColor[score.match_tier] || "bg-gray-100"}`}
              >
                {score.match_tier}
              </span>
              <span className="text-2xl font-bold">{score.overall_score}</span>
              <span className="text-gray-400 text-sm">/ 100</span>
            </div>

            <div className="grid grid-cols-5 gap-3 mb-4">
              {Object.entries(score.dimension_scores).map(([key, val]) => (
                <div key={key} className="text-center">
                  <div className="text-xs text-gray-500 mb-1">
                    {key.replace(/_/g, " ")}
                  </div>
                  <div className="text-lg font-semibold">{val}</div>
                </div>
              ))}
            </div>

            <div className="mb-4">
              <h3 className="text-sm font-medium text-gray-600 mb-1">
                Rationale
              </h3>
              <p className="text-sm text-gray-700">{score.rationale}</p>
            </div>

            {score.gaps.length > 0 && (
              <div className="mb-4">
                <h3 className="text-sm font-medium text-gray-600 mb-1">
                  Gaps
                </h3>
                <ul className="text-sm text-gray-700 list-disc pl-5">
                  {score.gaps.map((g, i) => (
                    <li key={i}>{g}</li>
                  ))}
                </ul>
              </div>
            )}

            {score.cover_letter_angles.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-600 mb-1">
                  Cover Letter Angles
                </h3>
                <ul className="text-sm text-gray-700 list-disc pl-5">
                  {score.cover_letter_angles.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-gray-400">
            Not scored yet. Click &quot;Score This Role&quot; to analyze match.
          </p>
        )}
      </section>

      {/* Interview Intel */}
      <section className="bg-white rounded-lg border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Interview Intel</h2>
          <button
            onClick={fetchIntel}
            disabled={fetchingIntel}
            className="text-xs px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {fetchingIntel
              ? "Fetching..."
              : intel.length > 0
                ? "Refresh Intel"
                : "Fetch Intel"}
          </button>
        </div>

        {intel.length > 0 ? (
          intel.map((item, idx) => (
            <div key={idx} className="mb-4">
              <p className="text-xs text-gray-400 mb-2">
                Role type: {item.role_type}
              </p>

              <div className="mb-3">
                <h3 className="text-sm font-medium text-gray-600 mb-1">
                  Interview Structure
                </h3>
                <p className="text-sm text-gray-700">
                  {item.interview_structure}
                </p>
              </div>

              {item.question_themes.length > 0 && (
                <div className="mb-3">
                  <h3 className="text-sm font-medium text-gray-600 mb-1">
                    Question Themes
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {item.question_themes.map((t, i) => (
                      <span
                        key={i}
                        className="text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {item.emphasis_areas.length > 0 && (
                <div className="mb-3">
                  <h3 className="text-sm font-medium text-gray-600 mb-1">
                    Emphasis Areas
                  </h3>
                  <ul className="text-sm text-gray-700 list-disc pl-5">
                    {item.emphasis_areas.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                </div>
              )}

              {item.culture_signals.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-600 mb-1">
                    Culture Signals
                  </h3>
                  <ul className="text-sm text-gray-700 list-disc pl-5">
                    {item.culture_signals.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))
        ) : (
          <p className="text-sm text-gray-400">
            No intel yet. Click &quot;Fetch Intel&quot; to gather interview
            preparation data.
          </p>
        )}
      </section>

      {/* Forge Session — Interview Prep Brief */}
      <section className="bg-white rounded-lg border border-gray-200 p-5 mt-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Interview Prep Brief</h2>
          <button
            onClick={generateForgeSession}
            disabled={generatingSession}
            className="text-xs px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
          >
            {generatingSession
              ? "Generating..."
              : session
                ? "Regenerate"
                : "Generate Prep Brief"}
          </button>
        </div>

        {session ? (
          <div className="space-y-5">
            <p className="text-xs text-gray-400">
              Generated{" "}
              {new Date(session.created_at).toLocaleDateString()} at{" "}
              {new Date(session.created_at).toLocaleTimeString()}
            </p>

            {/* Opening Pitch */}
            {session.session_config.opening_pitch && (
              <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-purple-800 mb-2">
                  Opening Pitch — &quot;Tell me about yourself&quot;
                </h3>
                <p className="text-sm text-purple-900 italic">
                  &ldquo;{session.session_config.opening_pitch}&rdquo;
                </p>
              </div>
            )}

            {/* Company Interview Philosophy */}
            {session.session_config.company_interview_philosophy && (
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-2">
                  Company Interview Philosophy
                </h3>
                <p className="text-sm text-gray-600 bg-gray-50 rounded p-3">
                  {session.session_config.company_interview_philosophy}
                </p>
              </div>
            )}

            {/* Question Themes */}
            {session.session_config.question_themes?.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-3">
                  Expected Question Themes
                </h3>
                <div className="space-y-3">
                  {session.session_config.question_themes.map((q, i) => (
                    <div
                      key={i}
                      className="border border-gray-200 rounded-lg p-4 bg-gray-50"
                    >
                      <div className="flex items-start gap-3">
                        <span className="text-xs font-bold text-white bg-blue-600 rounded-full w-6 h-6 flex items-center justify-center flex-shrink-0 mt-0.5">
                          {i + 1}
                        </span>
                        <div className="flex-1">
                          <h4 className="text-sm font-semibold text-gray-800">
                            {q.theme}
                          </h4>
                          <p className="text-sm text-gray-500 italic mt-1">
                            &ldquo;{q.likely_question}&rdquo;
                          </p>
                          <div className="mt-2 grid grid-cols-2 gap-3">
                            <div>
                              <span className="text-xs font-medium text-green-700 block mb-0.5">
                                Leverage from resume
                              </span>
                              <p className="text-sm text-gray-700">
                                {q.leverage_from_resume}
                              </p>
                            </div>
                            <div>
                              <span className="text-xs font-medium text-blue-700 block mb-0.5">
                                Directional angle
                              </span>
                              <p className="text-sm text-gray-700">
                                {q.directional_angle}
                              </p>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Resume Leverage Map */}
            {session.session_config.resume_leverage_map?.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-3">
                  Your Strongest Cards
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {session.session_config.resume_leverage_map.map((r, i) => (
                    <div
                      key={i}
                      className="border border-green-200 bg-green-50 rounded-lg p-3"
                    >
                      <h4 className="text-sm font-semibold text-green-800 mb-1">
                        {r.experience}
                      </h4>
                      <p className="text-sm text-green-700">
                        {r.why_it_maps}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Gap Mitigation */}
            {session.session_config.gap_mitigation?.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-3">
                  Gap Mitigation
                </h3>
                <div className="space-y-2">
                  {session.session_config.gap_mitigation.map((g, i) => (
                    <div
                      key={i}
                      className="border border-yellow-200 bg-yellow-50 rounded-lg p-3 flex gap-3"
                    >
                      <div className="flex-shrink-0">
                        <span className="text-xs font-medium text-yellow-800 bg-yellow-200 px-2 py-0.5 rounded">
                          Gap
                        </span>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-yellow-900">
                          {g.gap}
                        </p>
                        <p className="text-sm text-yellow-800 mt-1">
                          {g.strategy}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-gray-400">
            No prep brief yet. Click &quot;Generate Prep Brief&quot; to get a
            strategic interview preparation plan mapped to your resume.
          </p>
        )}
      </section>
    </main>
  );
}
