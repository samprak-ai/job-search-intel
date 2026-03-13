#!/usr/bin/env node

/**
 * Tailored Resume Generator
 *
 * Reads JSON from stdin: { profile, tailoring, company, title }
 * Outputs .docx bytes to stdout.
 *
 * Uses docx-js for professional Word document generation.
 */

const {
  Document, Packer, Paragraph, TextRun, AlignmentType, LevelFormat,
  TabStopType, TabStopPosition, BorderStyle, HeadingLevel,
  ExternalHyperlink,
} = require("docx");

// ── Read stdin ──────────────────────────────────────────────────────
async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

// ── Fuzzy matching for bullet priorities ─────────────────────────────
function normalizeText(s) {
  return s.toLowerCase().replace(/[^a-z0-9\s]/g, "").replace(/\s+/g, " ").trim();
}

function similarityScore(a, b) {
  const aNorm = normalizeText(a);
  const bNorm = normalizeText(b);
  // Check substring containment first
  if (aNorm.includes(bNorm) || bNorm.includes(aNorm)) return 0.9;
  // Word overlap ratio
  const aWords = new Set(aNorm.split(" "));
  const bWords = new Set(bNorm.split(" "));
  let overlap = 0;
  for (const w of aWords) if (bWords.has(w)) overlap++;
  const union = new Set([...aWords, ...bWords]).size;
  return union > 0 ? overlap / union : 0;
}

function findBulletAction(bulletText, bulletPriorities) {
  let bestMatch = null;
  let bestScore = 0;
  for (const bp of bulletPriorities) {
    const score = similarityScore(bulletText, bp.original);
    if (score > bestScore && score > 0.3) {
      bestScore = score;
      bestMatch = bp;
    }
  }
  return bestMatch;
}

// ── Section matching ─────────────────────────────────────────────────
function matchSectionToJob(sectionName, workHistory) {
  const sLower = sectionName.toLowerCase();
  let best = null;
  let bestScore = 0;
  for (const job of workHistory) {
    const keywords = (job.company + " " + job.title).toLowerCase().split(/\s+/);
    let score = 0;
    for (const kw of keywords) {
      if (kw.length > 2 && sLower.includes(kw)) score++;
    }
    if (score > bestScore) {
      bestScore = score;
      best = job;
    }
  }
  return bestScore > 0 ? best : null;
}

function matchSectionToProject(sectionName, projects) {
  const sLower = sectionName.toLowerCase();
  for (const proj of projects) {
    if (sLower.includes(proj.title.toLowerCase())) return proj;
    if (proj.subtitle && sLower.includes(proj.subtitle.toLowerCase())) return proj;
  }
  // Check keyword overlap
  let best = null;
  let bestScore = 0;
  for (const proj of projects) {
    const keywords = (proj.title + " " + (proj.subtitle || "")).toLowerCase().split(/\s+/);
    let score = 0;
    for (const kw of keywords) {
      if (kw.length > 2 && sLower.includes(kw)) score++;
    }
    if (score > bestScore) {
      bestScore = score;
      best = proj;
    }
  }
  return bestScore > 0 ? best : null;
}

// ── Formatting constants ─────────────────────────────────────────────
const FONT = "Arial";
const BODY_SIZE = 20;  // 10pt in half-points
const SMALL_SIZE = 18; // 9pt
const HEADING_SIZE = 22; // 11pt
const NAME_SIZE = 28;  // 14pt (half-points)
const SECTION_BORDER = {
  bottom: { style: BorderStyle.SINGLE, size: 4, color: "2E74B5", space: 1 },
};

// ── Document builders ────────────────────────────────────────────────

function buildHeader(profile, tailoring) {
  const children = [];

  // Name
  children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 40 },
    children: [new TextRun({ text: profile.name, font: FONT, size: NAME_SIZE, bold: true })],
  }));

  // Contact line
  const contactParts = [profile.location];
  if (profile.contact?.email) contactParts.push(profile.contact.email);
  if (profile.contact?.linkedin) contactParts.push(profile.contact.linkedin);
  if (profile.contact?.github) contactParts.push(profile.contact.github);

  children.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 80 },
    children: [new TextRun({
      text: contactParts.join("  \u00B7  "),
      font: FONT, size: SMALL_SIZE, color: "555555",
    })],
  }));

  // Tailored headline
  if (tailoring.headline_suggestion) {
    children.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 120 },
      children: [new TextRun({
        text: tailoring.headline_suggestion,
        font: FONT, size: BODY_SIZE, italics: true, color: "333333",
      })],
    }));
  }

  return children;
}

function buildSectionHeading(title) {
  return new Paragraph({
    spacing: { before: 200, after: 80 },
    border: SECTION_BORDER,
    children: [new TextRun({
      text: title.toUpperCase(),
      font: FONT, size: HEADING_SIZE, bold: true, color: "2E74B5",
    })],
  });
}

function buildSummary(tailoring, profile) {
  const text = tailoring.summary_rewrite || profile.summary || profile.experience_summary || "";
  return [
    buildSectionHeading("Professional Summary"),
    new Paragraph({
      spacing: { after: 80 },
      children: [new TextRun({ text, font: FONT, size: BODY_SIZE })],
    }),
  ];
}

function buildProjectSection(projects, tailoring) {
  const children = [buildSectionHeading("Independent AI Projects")];
  const bulletPriorities = tailoring.bullet_priorities || [];

  for (const proj of projects) {
    // Project title line
    const titleParts = [new TextRun({ text: proj.title, font: FONT, size: BODY_SIZE, bold: true })];
    if (proj.subtitle) {
      titleParts.push(new TextRun({ text: `  \u2014  ${proj.subtitle}`, font: FONT, size: BODY_SIZE }));
    }
    if (proj.url) {
      titleParts.push(new TextRun({ text: `  \u00B7  ${proj.url}`, font: FONT, size: SMALL_SIZE, color: "555555" }));
    }
    children.push(new Paragraph({ spacing: { before: 100, after: 20 }, children: titleParts }));

    // Description (possibly reworded)
    if (proj.description) {
      const action = findBulletAction(proj.description, bulletPriorities);
      const text = (action && action.reword_suggestion) ? action.reword_suggestion : proj.description;
      children.push(new Paragraph({
        spacing: { after: 20 },
        children: [new TextRun({ text, font: FONT, size: BODY_SIZE })],
      }));
    }

    // Stack line
    if (proj.stack) {
      children.push(new Paragraph({
        spacing: { after: 20 },
        children: [
          new TextRun({ text: "Stack:  ", font: FONT, size: SMALL_SIZE, bold: true, color: "555555" }),
          new TextRun({ text: proj.stack, font: FONT, size: SMALL_SIZE, color: "555555" }),
        ],
      }));
    }

    // Outcome line
    if (proj.outcome) {
      children.push(new Paragraph({
        spacing: { after: 40 },
        children: [
          new TextRun({ text: "Outcome:  ", font: FONT, size: SMALL_SIZE, bold: true, color: "555555" }),
          new TextRun({ text: proj.outcome, font: FONT, size: SMALL_SIZE, color: "555555" }),
        ],
      }));
    }
  }

  return children;
}

function buildWorkSection(workHistory, tailoring) {
  const children = [buildSectionHeading("Experience")];
  const bulletPriorities = tailoring.bullet_priorities || [];

  for (const job of workHistory) {
    // Job title + company line with right-aligned dates
    children.push(new Paragraph({
      spacing: { before: 100, after: 20 },
      tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
      children: [
        new TextRun({ text: `${job.company}  \u00B7  ${job.title}`, font: FONT, size: BODY_SIZE, bold: true }),
        new TextRun({ text: `\t${job.dates}`, font: FONT, size: SMALL_SIZE, color: "555555" }),
      ],
    }));

    // Process bullets: apply rewordings and reorder
    const leadWith = [];
    const normal = [];
    const deprioritized = [];

    for (const bullet of job.bullets) {
      const action = findBulletAction(bullet, bulletPriorities);
      if (action) {
        if (action.action === "lead_with") {
          leadWith.push(action.reword_suggestion || bullet);
        } else if (action.action === "reword") {
          normal.push(action.reword_suggestion || bullet);
        } else if (action.action === "deprioritize") {
          deprioritized.push(bullet);
        } else {
          normal.push(bullet);
        }
      } else {
        normal.push(bullet);
      }
    }

    const orderedBullets = [...leadWith, ...normal, ...deprioritized];

    for (const bullet of orderedBullets) {
      children.push(new Paragraph({
        numbering: { reference: "resume-bullets", level: 0 },
        spacing: { after: 20 },
        children: [new TextRun({ text: bullet, font: FONT, size: BODY_SIZE })],
      }));
    }
  }

  return children;
}

function buildCapabilities(profile, tailoring) {
  const children = [buildSectionHeading("Capabilities")];
  const highlight = new Set((tailoring.skills_to_highlight || []).map(s => s.toLowerCase()));
  const deprioritize = new Set((tailoring.skills_to_deprioritize || []).map(s => s.toLowerCase()));

  const caps = profile.capabilities || {};
  for (const [category, skills] of Object.entries(caps)) {
    // Filter out deprioritized skills
    const filteredSkills = skills.filter(s => !deprioritize.has(s.toLowerCase()));
    if (filteredSkills.length === 0) continue;

    const runs = [new TextRun({ text: `${category}:  `, font: FONT, size: BODY_SIZE, bold: true })];

    filteredSkills.forEach((skill, i) => {
      const isHighlighted = highlight.has(skill.toLowerCase());
      runs.push(new TextRun({
        text: skill + (i < filteredSkills.length - 1 ? ", " : ""),
        font: FONT, size: BODY_SIZE,
        bold: isHighlighted,
      }));
    });

    children.push(new Paragraph({ spacing: { after: 40 }, children: runs }));
  }

  // Add emphasized keywords as a separate line if they aren't already in capabilities
  const keywords = tailoring.keywords_to_emphasize || [];
  if (keywords.length > 0) {
    const allCaps = Object.values(caps).flat().map(s => s.toLowerCase());
    const newKeywords = keywords.filter(k => !allCaps.includes(k.toLowerCase()));
    if (newKeywords.length > 0) {
      children.push(new Paragraph({
        spacing: { after: 40 },
        children: [
          new TextRun({ text: "Key Focus Areas:  ", font: FONT, size: BODY_SIZE, bold: true }),
          new TextRun({ text: newKeywords.join(", "), font: FONT, size: BODY_SIZE }),
        ],
      }));
    }
  }

  return children;
}

function buildEducation(profile) {
  const children = [buildSectionHeading("Education")];
  const details = profile.education_details || [];

  for (const edu of details) {
    const parts = [new TextRun({
      text: edu.institution,
      font: FONT, size: BODY_SIZE, bold: true,
    })];

    if (edu.location) {
      parts.push(new TextRun({
        text: `\t${edu.location}`,
        font: FONT, size: SMALL_SIZE, color: "555555",
      }));
    }

    children.push(new Paragraph({
      spacing: { before: 60, after: 10 },
      tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
      children: parts,
    }));

    const degreeParts = [new TextRun({ text: edu.degree, font: FONT, size: BODY_SIZE })];
    if (edu.gpa) {
      degreeParts.push(new TextRun({ text: `  \u00B7  ${edu.gpa}`, font: FONT, size: SMALL_SIZE, color: "555555" }));
    }
    children.push(new Paragraph({ spacing: { after: 40 }, children: degreeParts }));
  }

  return children;
}

// ── Section dispatcher ───────────────────────────────────────────────

const KNOWN_SECTIONS = {
  "professional summary": "summary",
  "summary": "summary",
  "capabilities": "capabilities",
  "technical skills": "capabilities",
  "skills": "capabilities",
  "education": "education",
};

const PROJECT_KEYWORDS = ["independent", "project", "ai project", "personal project", "genai", "forge"];
const EXPERIENCE_KEYWORDS = ["experience", "work history", "employment", "aws"];

function buildSections(profile, tailoring) {
  const sectionOrder = tailoring.section_order || [
    "Professional Summary",
    "Independent AI Projects",
    "Experience",
    "Capabilities",
    "Education",
  ];

  const all = [];
  const renderedJobs = new Set();
  let renderedProjects = false;
  let renderedCaps = false;
  let renderedEdu = false;
  let renderedSummary = false;

  for (const section of sectionOrder) {
    const sLower = section.toLowerCase();
    const known = KNOWN_SECTIONS[sLower];

    if (known === "summary" && !renderedSummary) {
      all.push(...buildSummary(tailoring, profile));
      renderedSummary = true;
      continue;
    }

    if (known === "capabilities" && !renderedCaps) {
      all.push(...buildCapabilities(profile, tailoring));
      renderedCaps = true;
      continue;
    }

    if (known === "education" && !renderedEdu) {
      all.push(...buildEducation(profile));
      renderedEdu = true;
      continue;
    }

    // Check if it's a project section
    if (PROJECT_KEYWORDS.some(kw => sLower.includes(kw)) && !renderedProjects) {
      all.push(...buildProjectSection(profile.projects || [], tailoring));
      renderedProjects = true;
      continue;
    }

    // Check if it's a work experience section
    if (EXPERIENCE_KEYWORDS.some(kw => sLower.includes(kw))) {
      // Render all work history under this section
      const jobs = (profile.work_history || []).filter(j => !renderedJobs.has(j.title));
      if (jobs.length > 0) {
        all.push(...buildWorkSection(jobs, tailoring));
        jobs.forEach(j => renderedJobs.add(j.title));
      }
      continue;
    }

    // Try matching to a specific job
    const matchedJob = matchSectionToJob(section, profile.work_history || []);
    if (matchedJob && !renderedJobs.has(matchedJob.title)) {
      all.push(...buildWorkSection([matchedJob], tailoring));
      renderedJobs.add(matchedJob.title);
      continue;
    }

    // Try matching to a project
    const matchedProj = matchSectionToProject(section, profile.projects || []);
    if (matchedProj && !renderedProjects) {
      all.push(...buildProjectSection(profile.projects || [], tailoring));
      renderedProjects = true;
      continue;
    }
  }

  // Ensure nothing is missed — render unrendered sections at the end
  if (!renderedSummary) all.push(...buildSummary(tailoring, profile));
  if (!renderedProjects && (profile.projects || []).length > 0) {
    all.push(...buildProjectSection(profile.projects, tailoring));
  }
  const unrenderedJobs = (profile.work_history || []).filter(j => !renderedJobs.has(j.title));
  if (unrenderedJobs.length > 0) all.push(...buildWorkSection(unrenderedJobs, tailoring));
  if (!renderedCaps) all.push(...buildCapabilities(profile, tailoring));
  if (!renderedEdu) all.push(...buildEducation(profile));

  return all;
}

// ── Main ─────────────────────────────────────────────────────────────

async function main() {
  const input = await readStdin();
  const { profile, tailoring } = input;

  const children = [
    ...buildHeader(profile, tailoring),
    ...buildSections(profile, tailoring),
  ];

  const doc = new Document({
    numbering: {
      config: [{
        reference: "resume-bullets",
        levels: [{
          level: 0,
          format: LevelFormat.BULLET,
          text: "\u2022",
          alignment: AlignmentType.LEFT,
          style: {
            paragraph: { indent: { left: 360, hanging: 200 } },
          },
        }],
      }],
    },
    sections: [{
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 720, right: 720, bottom: 720, left: 720 },
        },
      },
      children,
    }],
  });

  const buffer = await Packer.toBuffer(doc);
  process.stdout.write(buffer);
}

main().catch((err) => {
  process.stderr.write(`Error: ${err.message}\n`);
  process.exit(1);
});
