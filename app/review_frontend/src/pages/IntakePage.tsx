import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { acceptIntake, fetchIntake, intakePdfUrl, rejectIntake } from "../api";
import type { IntakeDetail } from "../types";

export function IntakePage() {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState<IntakeDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchIntake(id).then(setData).catch((e) => setErr(String(e)));
  }, [id]);

  if (err) return <div className="page"><div className="empty-state">{err}</div></div>;
  if (!data) return <div className="page"><div className="loading-rail"><span className="spinner" /> loading…</div></div>;

  const accept = async () => {
    setBusy(true);
    try { nav(`/project/${await acceptIntake(id)}`); }
    catch (e) { setErr(String(e)); setBusy(false); }
  };

  const reject = async () => {
    const reason = window.prompt("Reason for rejecting (optional):") ?? "";
    setBusy(true);
    try { await rejectIntake(id, reason); nav("/"); }
    catch (e) { setErr(String(e)); setBusy(false); }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div className="eyebrow">pending intake · {data.level} / {data.conn_type}</div>
        <h1>{data.name || "(unnamed submission)"}</h1>
        <p>From {data.intake.sender} — "{data.intake.subject}". Applicant: {data.applicant}.</p>
      </div>

      {data.intake.flags.length > 0 && (
        <div className="empty-state">
          <div className="big">Extraction flags</div>
          <ul style={{ textAlign: "left", display: "inline-block" }}>
            {data.intake.flags.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </div>
      )}

      <div className="intake-grid">
        <div>
          <h3 className="intake-col-head">Extracted sections</h3>
          {data.sections.map((s) => (
            <div className="section-card" key={s.id}>
              <div className="row-between">
                <strong>{s.title}</strong>
                <span className={`chip chip-confidence chip-${s.confidence}`}>{s.confidence}</span>
              </div>
              <p className="muted intake-req">{s.requirement}</p>
              <p className="intake-submitted">{s.submitted || <em>— no answer extracted —</em>}</p>
              {s.docs.length > 0 && <div className="muted intake-docs">docs: {s.docs.join(", ")}</div>}
            </div>
          ))}
          {data.sections.length === 0 && <p className="muted">No sections extracted.</p>}
        </div>
        <div>
          <h3 className="intake-col-head">Original attachments</h3>
          {data.documents.length === 0 && <p className="muted">No PDF attachments.</p>}
          {data.documents.map((d) => (
            <a className="doc-link" key={d.name} href={intakePdfUrl(id, d.name)}
               target="_blank" rel="noreferrer">{d.name}</a>
          ))}
        </div>
      </div>

      <div className="action-bar">
        <button className="btn primary" disabled={busy} onClick={accept}>
          Accept → create application
        </button>
        <button className="btn" disabled={busy} onClick={reject}>
          Reject
        </button>
      </div>
    </div>
  );
}
