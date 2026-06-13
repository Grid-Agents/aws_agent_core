import { useState } from "react";
import { pdfUrl } from "../api";
import type { ProjectDetail } from "../types";

export function DocumentsTab({ project }: { project: ProjectDetail }) {
  const files = [
    { name: "00_application_form.pdf", label: "Application form", tag: "form" },
    ...project.documents.map((d) => ({ name: d.name, label: d.name, tag: "supporting" })),
  ];
  const [active, setActive] = useState(files[0].name);

  return (
    <div className="doclist">
      <div className="files">
        {files.map((f) => (
          <button
            key={f.name}
            className={`docfile ${active === f.name ? "active" : ""}`}
            onClick={() => setActive(f.name)}
          >
            <span className="ico" />
            <span>
              <span className="fname">{f.label}</span>
              <br />
              <span className="ftag">{f.tag}</span>
            </span>
          </button>
        ))}
      </div>
      <div className="docframe">
        {active ? (
          <iframe title={active} src={pdfUrl(project.id, active)} />
        ) : (
          <div className="empty">Select a document</div>
        )}
      </div>
    </div>
  );
}
