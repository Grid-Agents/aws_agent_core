import { Fragment, type ReactNode } from "react";

/**
 * Intentionally tiny Markdown renderer for agent answers — handles the subset
 * the review/co-pilot prompts actually produce: ## / ### headings, **bold**,
 * `- ` bullet lists, blank-line paragraphs, and [E1, E2] citation tags. Renders
 * to React nodes (no innerHTML).
 */
function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  // Split on **bold** and [E#] citation tags, keeping delimiters.
  const parts = text.split(/(\*\*[^*]+\*\*|\[E[0-9, ]+\])/g);
  parts.forEach((p, i) => {
    if (!p) return;
    if (p.startsWith("**") && p.endsWith("**")) {
      out.push(<strong key={`${keyBase}-b${i}`}>{p.slice(2, -2)}</strong>);
    } else if (/^\[E[0-9, ]+\]$/.test(p)) {
      out.push(<span className="md-cite" key={`${keyBase}-c${i}`}>{p}</span>);
    } else {
      out.push(<Fragment key={`${keyBase}-t${i}`}>{p}</Fragment>);
    }
  });
  return out;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let para: string[] = [];

  const flushPara = (k: string) => {
    if (para.length) {
      blocks.push(<p key={k}>{inline(para.join(" "), k)}</p>);
      para = [];
    }
  };
  const flushList = (k: string) => {
    if (list.length) {
      blocks.push(
        <ul key={k}>
          {list.map((li, i) => <li key={`${k}-${i}`}>{inline(li, `${k}-${i}`)}</li>)}
        </ul>,
      );
      list = [];
    }
  };

  lines.forEach((raw, idx) => {
    const line = raw.trim();
    const k = `b${idx}`;
    if (!line) {
      flushPara(k);
      flushList(k);
    } else if (/^(---+|\*\*\*+)$/.test(line)) {
      flushPara(k); flushList(k);
      blocks.push(<hr key={k} className="md-hr" />);
    } else if (line.startsWith("### ")) {
      flushPara(k); flushList(k);
      blocks.push(<h5 key={k}>{inline(line.slice(4), k)}</h5>);
    } else if (line.startsWith("## ")) {
      flushPara(k); flushList(k);
      blocks.push(<h4 key={k}>{inline(line.slice(3), k)}</h4>);
    } else if (line.startsWith("# ")) {
      flushPara(k); flushList(k);
      blocks.push(<h4 key={k}>{inline(line.slice(2), k)}</h4>);
    } else if (/^[-*]\s+/.test(line)) {
      flushPara(k);
      list.push(line.replace(/^[-*]\s+/, ""));
    } else {
      flushList(k);
      para.push(line);
    }
  });
  flushPara("end"); flushList("end");

  return <div className="md">{blocks}</div>;
}
