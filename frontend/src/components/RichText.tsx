import type { ReactNode } from "react";

/**
 * Minimal, safe renderer for model answers: **bold**, "- " bullet lists, paragraphs and [n] citation
 * markers. It builds React elements (never raw HTML), so model output cannot inject markup.
 */
function inline(text: string, key: string): ReactNode[] {
  return text
    .split(/(\*\*[^*]+\*\*|\[\d+\])/g)
    .filter(Boolean)
    .map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return (
          <strong key={`${key}-${i}`} className="font-semibold text-ink">
            {part.slice(2, -2)}
          </strong>
        );
      }
      const cite = /^\[(\d+)\]$/.exec(part);
      if (cite) {
        return (
          <sup
            key={`${key}-${i}`}
            className="ml-0.5 rounded bg-brand-50 px-1 text-[10px] font-semibold text-brand-700"
            aria-label={`source ${cite[1]}`}
          >
            {cite[1]}
          </sup>
        );
      }
      return part;
    });
}

export function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      const items = list;
      blocks.push(
        <ul key={`ul-${blocks.length}`} className="list-disc space-y-1 pl-5">
          {items.map((item, i) => (
            <li key={i}>{inline(item, `li-${blocks.length}-${i}`)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = /^(?:[-*•]|\d+\.)\s+(.*)$/.exec(line);
    if (bullet) {
      list.push(bullet[1]!);
      continue;
    }
    flush();
    if (!line) continue;
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    blocks.push(
      <p key={`p-${blocks.length}`} className={heading ? "font-semibold text-ink" : undefined}>
        {inline(heading ? heading[1]! : line, `p-${blocks.length}`)}
      </p>,
    );
  }
  flush();
  return <div className="space-y-2 text-sm leading-relaxed text-ink/90">{blocks}</div>;
}
