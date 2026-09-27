import { useEffect, useState } from "react";
import "../../../app/agent.js";

// Same agent client as the static app (app/agent.js): asks the backend's
// /recommend (Hugging Face draft + hallucination guard) when it's running,
// otherwise shows the identical deterministic template computed here.
const AG = globalThis.GridlockAgent;
const API_BASE = AG.apiBase(import.meta.env.VITE_API_BASE || "http://localhost:8001");
const results = new Map(); // `${dataset}:${overlap id}` -> result

export default function AgentRecommendation({ overlap, dataset }) {
  const key = overlap ? `${dataset}:${overlap.id}` : null;
  const [result, setResult] = useState(() => (key ? results.get(key) : null));

  useEffect(() => {
    if (!overlap) return;
    let cancelled = false;
    if (results.has(key)) {
      setResult(results.get(key));
      return;
    }
    setResult(null);
    AG.getRecommendation(API_BASE, overlap, dataset).then((r) => {
      results.set(key, r);
      if (!cancelled) setResult(r);
    });
    return () => {
      cancelled = true;
    };
  }, [key, overlap, dataset]);

  if (!overlap) return null;

  let body;
  if (!result) {
    body = <div className="cost-box wx-status">Asking the coordination agent…</div>;
  } else {
    const d = AG.describe(result);
    const rejected = result.guard?.rejected_drafts || [];
    body = (
      <div className="cost-box ai-box">
        <span className={`ai-badge ai-${d.tone}`}>{d.title}</span>
        <p className="ai-text">{result.recommendation}</p>
        <div className="ai-detail">{d.detail}</div>
        {rejected.length > 0 && (
          <details className="ai-rejected">
            <summary>See the draft the fact-check blocked</summary>
            {rejected.map((t, i) => (
              <div key={i}>
                <div className="ai-draft-label">{AG.draftLabel(i)}</div>
                <blockquote>{t}</blockquote>
              </div>
            ))}
          </details>
        )}
        <div className="note">Recommends only: the utilities' planners make the final call.</div>
      </div>
    );
  }

  return (
    <section className="ai-recommend">
      <h2>AI Coordination Recommendation</h2>
      {body}
    </section>
  );
}
