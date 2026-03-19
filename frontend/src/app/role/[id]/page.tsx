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

type BulletPriority = {
  original: string;
  action: "lead_with" | "reword" | "deprioritize";
  reword_suggestion: string | null;
  why: string;
};

type ResumeTailoring = {
  headline_suggestion: string;
  summary_rewrite: string;
  section_order: string[];
  bullet_priorities: BulletPriority[];
  keywords_to_emphasize: string[];
  skills_to_highlight: string[];
  skills_to_deprioritize: string[];
};

type ResumeTailor = {
  id: string;
  role_id: string;
  tailoring: ResumeTailoring;
  created_at: string;
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
  resume_tailor: ResumeTailor | null;
  session: Session | null;
  is_live: boolean | null;
  last_checked_at: string | null;
};

export default function RoleDetail() {
  const params = useParams();
  const id = params.id as string;
  const [role, setRole] = useState<RoleData | null>(null);
  const [loading, setLoading] = useState(true);
  const [scoring, setScoring] = useState(false);
  const [fetchingIntel, setFetchingIntel] = useState(false);
  const [generatingSession, setGeneratingSession] = useState(false);
  const [tailoringLoading, setTailoringLoading] = useState(false);
  const [downloadingResume, setDownloadingResume] = useState(false);

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

  async function generateTailoring() {
    setTailoringLoading(true);
    try {
      await fetch(`${API}/resume-tailor/${id}`, { method: "POST" });
      await fetchRole();
    } catch (e) {
      console.error("Resume tailoring generation failed:", e);
    }
    setTailoringLoading(false);
  }

  async function downloadResume() {
    setDownloadingResume(true);
    try {
      const res = await fetch(`${API}/resume-tailor/${id}/download`);
      if (!res.ok) {
        console.error("Download failed:", res.statusText);
        setDownloadingResume(false);
        return;
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Sam_Prakash_Resume_${role?.company?.replace(/\s+/g, "_") || "Role"}.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Resume download failed:", e);
    }
    setDownloadingResume(false);
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
  const tailor = role.resume_tailor;
  const session = role.session;
  const currentStatus = role.application_status || "unreviewed";

  const bulletActionStyle: Record<string, string> = {
    lead_with: "border-green-200 bg-green-50",
    reword: "border-blue-200 bg-blue-50",
    deprioritize: "border-gray-200 bg-gray-50",
  };
  const bulletActionLabel: Record<string, { text: string; color: string }> = {
    lead_with: { text: "Lead With", color: "bg-green-600 text-white" },
    reword: { text: "Reword", color: "bg-blue-600 text-white" },
    deprioritize: { text: "Deprioritize", color: "bg-gray-400 text-white" },
  };

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

      {/* Stale posting warning */}
      {role.is_live === false && (
        <div className="flex items-center gap-3 px-4 py-3 mb-6 bg-amber-50 border border-amber-200 rounded-lg text-amber-800 text-sm">
          <svg className="w-5 h-5 flex-shrink-0 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
          </svg>
          <span>
            This posting may no longer be active — the original URL returned an error
            {role.last_checked_at && (
              <> on {new Date(role.last_checked_at).toLocaleDateString()}</>
            )}
            .
          </span>
        </div>
      )}

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

      {/* Resume Tailoring */}
      <section className="bg-white rounded-lg border border-gray-200 p-5 mt-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Resume Tailoring</h2>
          <div className="flex items-center gap-2">
            {tailor && (
              <button
                onClick={downloadResume}
                disabled={downloadingResume}
                className="text-xs px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 flex items-center gap-1"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                {downloadingResume ? "Downloading..." : "Download Resume"}
              </button>
            )}
            <button
              onClick={generateTailoring}
              disabled={tailoringLoading}
              className="text-xs px-3 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
            >
              {tailoringLoading
                ? "Generating..."
                : tailor
                  ? "Regenerate"
                  : "Generate Resume Tailoring"}
            </button>
          </div>
        </div>

        {tailor ? (
          <div className="space-y-5">
            <p className="text-xs text-gray-400">
              Generated{" "}
              {new Date(tailor.created_at).toLocaleDateString()} at{" "}
              {new Date(tailor.created_at).toLocaleTimeString()}
            </p>

            {/* Headline Suggestion */}
            {tailor.tailoring.headline_suggestion && (
              <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-indigo-800 mb-2">
                  Headline Positioning
                </h3>
                <p className="text-sm text-indigo-900 font-medium">
                  {tailor.tailoring.headline_suggestion}
                </p>
              </div>
            )}

            {/* Summary Rewrite */}
            {tailor.tailoring.summary_rewrite && (
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-2">
                  Tailored Summary
                </h3>
                <p className="text-sm text-gray-600 bg-gray-50 rounded p-3 italic">
                  {tailor.tailoring.summary_rewrite}
                </p>
              </div>
            )}

            {/* Section Order */}
            {tailor.tailoring.section_order?.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-2">
                  Optimal Section Order
                </h3>
                <ol className="text-sm text-gray-700 list-decimal pl-5 space-y-1">
                  {tailor.tailoring.section_order.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
              </div>
            )}

            {/* Bullet Priorities */}
            {tailor.tailoring.bullet_priorities?.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-3">
                  Bullet Point Priorities
                </h3>
                <div className="space-y-3">
                  {tailor.tailoring.bullet_priorities.map((b, i) => (
                    <div
                      key={i}
                      className={`border rounded-lg p-4 ${bulletActionStyle[b.action] || "border-gray-200 bg-gray-50"}`}
                    >
                      <div className="flex items-start gap-3">
                        <span
                          className={`text-xs font-medium px-2 py-0.5 rounded flex-shrink-0 mt-0.5 ${bulletActionLabel[b.action]?.color || "bg-gray-400 text-white"}`}
                        >
                          {bulletActionLabel[b.action]?.text || b.action}
                        </span>
                        <div className="flex-1">
                          <p className="text-sm text-gray-800 font-medium">
                            {b.original}
                          </p>
                          {b.reword_suggestion && (
                            <p className="text-sm text-gray-600 mt-1 italic">
                              &rarr; {b.reword_suggestion}
                            </p>
                          )}
                          <p className="text-xs text-gray-500 mt-1">
                            {b.why}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Keywords & Skills */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Keywords to Emphasize */}
              {tailor.tailoring.keywords_to_emphasize?.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 mb-2">
                    Keywords to Emphasize
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {tailor.tailoring.keywords_to_emphasize.map((k, i) => (
                      <span
                        key={i}
                        className="text-xs px-2.5 py-1 bg-indigo-100 text-indigo-700 rounded-full font-medium"
                      >
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Skills to Highlight */}
              {tailor.tailoring.skills_to_highlight?.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 mb-2">
                    Skills to Highlight
                  </h3>
                  <div className="flex flex-wrap gap-1.5">
                    {tailor.tailoring.skills_to_highlight.map((s, i) => (
                      <span
                        key={i}
                        className="text-xs px-2.5 py-1 bg-green-100 text-green-700 rounded-full font-medium"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Skills to Deprioritize */}
            {tailor.tailoring.skills_to_deprioritize?.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-2">
                  Skills to Deprioritize
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {tailor.tailoring.skills_to_deprioritize.map((s, i) => (
                    <span
                      key={i}
                      className="text-xs px-2.5 py-1 bg-gray-100 text-gray-500 rounded-full line-through"
                    >
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-gray-400">
            No tailoring yet. Click &quot;Generate Resume Tailoring&quot; to get
            role-specific advice on how to prioritize and reframe your resume.
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
