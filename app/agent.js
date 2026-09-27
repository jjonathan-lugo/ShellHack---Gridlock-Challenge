// Coordination-recommendation agent, browser side (add-on ideas #3–#5).
//
// The real agent lives in backend/agent/recommend.py: a Hugging Face LLM
// drafts the recommendation and a fact-check rejects any draft that misstates
// the distance (retrying once, then falling back to a template). This file
//   * asks the backend's /recommend for the selected pair when it's running, and
//   * otherwise shows the same deterministic template, computed here, so the
//     panel always has something honest to show — even offline.
// templateRecommendation() must match the Python template word for word;
// backend/tests/test_agent_ui.py checks that on every overlap.
//
// Shared by the static app (window.GridlockAgent) and the React app (import).

(function (root) {
  const MI_TO_KM = 1.60934;

  // Mirrors backend/estimate/cost_impact.py ASSUMPTIONS.
  const A = {
    yardLow: 120000, yardHigh: 180000, shareLow: 0.4, shareHigh: 0.6,
    rowLow: 260000, rowHigh: 420000, rowShare: 0.35,
    crewLow: 40000, crewHigh: 75000, crewShare: 0.25,
  };

  const TIER_ACTIONS = {
    coordinate:
      "These projects touch or cross, so coordination isn't optional: align outage " +
      "windows and agree on crossing structures before either design is finalized.",
    land:
      "At this range the two projects can share the corridor itself — right-of-way, " +
      "access roads, and permitting are worth negotiating jointly rather than twice.",
    logistics:
      "Close enough to share site logistics: a single laydown yard and consolidated " +
      "material deliveries would serve both jobs.",
    crew:
      "Within range to share crews and specialized equipment if the schedules are " +
      "sequenced deliberately rather than left to chance.",
  };

  function tierOf(distanceMi) {
    const km = distanceMi * MI_TO_KM;
    if (km < 0.1) return "coordinate";
    if (km < 1.6) return "land";
    if (km < 8) return "logistics";
    if (km < 40) return "crew";
    return "none";
  }

  function estimate(tier) {
    if (tier === "coordinate" || tier === "land")
      return { low: A.rowLow * A.rowShare, high: A.rowHigh * A.rowShare, basis: "shared right-of-way, access roads, and permitting" };
    if (tier === "logistics")
      return { low: A.yardLow * A.shareLow, high: A.yardHigh * A.shareHigh, basis: "one shared laydown yard / site mobilization instead of two" };
    if (tier === "crew")
      return { low: A.crewLow * A.crewShare, high: A.crewHigh * A.crewShare, basis: "shared crew and specialized equipment mobilization" };
    return null;
  }

  // Python's round() rounds halves to even; match it so "$Nk" never differs.
  function roundHalfEven(x) {
    const f = Math.floor(x);
    const d = x - f;
    if (d > 0.5) return f + 1;
    if (d < 0.5) return f;
    return f % 2 === 0 ? f : f + 1;
  }

  // Python's str(float): 4.0 -> "4.0", 4.09 -> "4.09".
  function pyNum(x) {
    return Number.isInteger(x) ? x.toFixed(1) : String(x);
  }

  function timingNote(days) {
    if (days == null) return "In-service dates aren't both known, so the schedule fit needs checking by hand.";
    const years = days / 365;
    if (days <= 180)
      return `Their in-service dates are only ${days} days apart, so the build windows likely overlap — this is the strongest kind of candidate.`;
    if (years <= 2)
      return `Their in-service dates are about ${years.toFixed(1)} years apart, so shared resourcing would need one side to shift phasing, but it's within reach.`;
    return `Their in-service dates are roughly ${years.toFixed(1)} years apart, so treat this as a geographic opportunity (shared corridor or access) rather than a shared-crew one.`;
  }

  // `overlap` needs project_name_a/b, utility_a/b, distance_mi, and
  // time_gap_days (or the spreadsheet's "time_gap (day)").
  function templateRecommendation(o) {
    const tier = o.tier || tierOf(o.distance_mi);
    const gap = o.time_gap_days !== undefined ? o.time_gap_days : o["time_gap (day)"];
    const parts = [
      `${o.project_name_a} (${o.utility_a}) and ${o.project_name_b} (${o.utility_b}) are ${pyNum(o.distance_mi)} mi apart.`,
      TIER_ACTIONS[tier] || "Worth a planner's review for shared resourcing.",
      timingNote(gap),
    ];
    const est = estimate(tier);
    if (est) {
      parts.push(
        `Rough order of magnitude: $${roundHalfEven(est.low / 1000)}k–$${roundHalfEven(est.high / 1000)}k from ${est.basis} ` +
          "(illustrative assumptions, not an engineering estimate)."
      );
    }
    parts.push("Final coordination decisions rest with the utilities' own planners.");
    return parts.join(" ");
  }

  // Where the backend is: ?api=... overrides; default is run-app.sh's port.
  function apiBase(fallback) {
    try {
      const q = new URLSearchParams(root.location ? root.location.search : "").get("api");
      if (q) return q.replace(/\/$/, "");
    } catch (_) {
      /* not in a browser */
    }
    return fallback;
  }

  let reachable = null; // cached /health result
  async function backendUp(base) {
    if (reachable !== null) return reachable;
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 1500);
      const res = await fetch(`${base}/health`, { signal: ctrl.signal });
      clearTimeout(t);
      reachable = res.ok;
    } catch (_) {
      reachable = false;
    }
    return reachable;
  }

  // -> { recommendation, source, guard, model, llm_unavailable_reason, origin }
  // origin: "backend" | "offline". Never throws: falls back to the template.
  async function getRecommendation(base, overlap, dataset) {
    if (base && (await backendUp(base))) {
      try {
        const q = new URLSearchParams({ project_id_a: overlap.project_id_a, project_id_b: overlap.project_id_b, dataset: dataset || "curated" });
        const res = await fetch(`${base}/recommend?${q}`);
        if (res.ok) return { ...(await res.json()), origin: "backend" };
      } catch (_) {
        /* fall through to the offline template */
      }
    }
    return { recommendation: templateRecommendation(overlap), source: "template", guard: null, origin: base ? "offline" : "hosted" };
  }

  // How to label a result for a human: { tone, title, detail }.
  function describe(r) {
    const g = r.guard || {};
    const rejected = (g.rejected_drafts || []).length;
    const model = r.model ? r.model.split("/").pop() : "the AI model";
    if (r.source === "llm" && rejected)
      return { tone: "good", title: "AI draft · corrected itself", detail: `The fact-check rejected ${rejected === 1 ? "its first draft" : `${rejected} drafts`} for misstating the distance; ${model} then gave the exact ${g.expected} mi.` };
    if (r.source === "llm")
      return { tone: "good", title: "AI draft · fact-checked", detail: `Written by ${model} via Hugging Face. Its distance matches the data (${g.expected} mi).` };
    if (r.source === "template_after_failed_guard" && rejected)
      return { tone: "warn", title: "AI draft rejected · verified template shown", detail: `${model} misstated the distance (expected ${g.expected} mi), so its draft was blocked instead of reaching a planner.` };
    if (r.source === "template_after_failed_guard")
      return { tone: "warn", title: "AI unavailable · template shown", detail: `The model call failed${g.error ? ` (${g.error.split(":")[0]})` : ""}, so the deterministic template is shown.` };
    if (r.origin === "hosted")
      return { tone: "muted", title: "Template · public demo", detail: "Live AI drafts (Llama 3.1 via Hugging Face, with the fact-check) run when the app is started locally with a Hugging Face token; see the README. This is the same verified template the AI falls back to." };
    if (r.origin === "offline")
      return { tone: "muted", title: "Template · AI backend not running", detail: "Start ./run-app.sh (it starts the backend) with HF_TOKEN set for AI drafts." };
    return { tone: "muted", title: "Template · no HF_TOKEN", detail: "Set HF_TOKEN before ./run-app.sh for AI drafts; this is the deterministic template." };
  }

  const draftLabel = (i) => (i === 0 ? "First draft" : i === 1 ? "After being told to fix it" : `Retry ${i}`);

  const api = { templateRecommendation, getRecommendation, describe, apiBase, tierOf, draftLabel };
  root.GridlockAgent = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
