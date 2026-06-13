import { figureUrl } from "../api";
import type { Evidence } from "../types";

export function Citations({ items }: { items: Evidence[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="cites">
      <h4>Cited evidence · {items.length}</h4>
      {items.map((c, i) => {
        const fig = c.metadata?.figures?.[0];
        const img = figureUrl(fig?.image_path || fig?.local_path);
        return (
          <div className="cite" key={c.id || i}>
            <div className="top">
              <span className="tag">{c.id || `E${i + 1}`}</span>
              <span className="src">{c.title || c.source_path || "source"}</span>
              {c.page != null && <span className="pg">p.{c.page}</span>}
            </div>
            {c.span_text && <div className="span">{c.span_text.slice(0, 360)}</div>}
            {img && (
              <figure>
                <img src={img} alt={fig?.description || "cited figure"} loading="lazy" />
              </figure>
            )}
          </div>
        );
      })}
    </div>
  );
}
