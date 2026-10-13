import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Quote, Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { AskResponse, Citation } from "../lib/types";
import { RichText } from "./RichText";
import { ErrorNote } from "./ui";

export function AnswerView({
  answer,
  citations,
  onCite,
}: {
  answer: string;
  citations: Citation[];
  onCite?: (c: Citation) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex gap-3">
        <div className="grid size-7 shrink-0 place-items-center rounded-full bg-brand-50 text-brand-600">
          <Bot className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <RichText text={answer} />
        </div>
      </div>
      {citations.length > 0 && (
        <ol className="ml-10 space-y-2">
          {citations.map((c, i) => (
            <li key={`${c.chunk_id}-${i}`} className="rounded-lg border border-line bg-paper/50 p-3 text-xs">
              <div className="mb-1 flex items-center gap-1.5 font-medium text-muted">
                <Quote className="size-3.5" />
                {onCite ? (
                  <button type="button" className="text-brand-700 hover:underline" onClick={() => onCite(c)}>
                    {c.document_title} · section {c.chunk_index + 1}
                  </button>
                ) : (
                  <Link
                    to={`/documents/${c.document_id}?quote=${encodeURIComponent(c.quote.slice(0, 160))}`}
                    className="text-brand-700 hover:underline"
                  >
                    {c.document_title} · section {c.chunk_index + 1}
                  </Link>
                )}
              </div>
              <blockquote className="text-ink/80">"{c.quote}"</blockquote>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function AskBox({
  documentId,
  placeholder,
  suggestions = [],
  onCite,
}: {
  documentId?: string;
  placeholder: string;
  suggestions?: string[];
  onCite?: (c: Citation) => void;
}) {
  const qc = useQueryClient();
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<(AskResponse & { question: string }) | null>(null);

  const ask = useMutation({
    mutationFn: (q: string) => api.ask(q, documentId),
    onSuccess: (res, q) => {
      setResult({ ...res, question: q });
      void qc.invalidateQueries({ queryKey: ["history"] });
    },
  });

  const submit = (e?: FormEvent, q = question) => {
    e?.preventDefault();
    if (q.trim().length >= 3) ask.mutate(q.trim());
  };

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="flex gap-2">
        <input
          className="input"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={placeholder}
          aria-label="Question"
        />
        <button className="btn-primary shrink-0" disabled={ask.isPending || question.trim().length < 3} type="submit">
          <Send className="size-4" />
          {ask.isPending ? "Thinking..." : "Ask"}
        </button>
      </form>
      {suggestions.length > 0 && !result && (
        <div className="flex flex-wrap gap-2">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              className="rounded-full border border-line bg-white px-3 py-1 text-xs text-muted hover:border-brand-200 hover:text-ink"
              onClick={() => {
                setQuestion(s);
                submit(undefined, s);
              }}
            >
              {s}
            </button>
          ))}
        </div>
      )}
      <ErrorNote error={ask.error} />
      {result && (
        <div className="rounded-xl border border-line bg-white p-4" data-testid="answer">
          <div className="mb-3 text-xs font-medium text-muted">Q: {result.question}</div>
          <AnswerView answer={result.answer} citations={result.citations} onCite={onCite} />
          <div className="mt-3 text-right text-[11px] text-muted">
            {result.provider === "demo" ? "Offline demo model" : "Claude"} · {result.latency_ms} ms
            {result.cost_usd > 0 && ` · $${result.cost_usd.toFixed(4)}`}
          </div>
        </div>
      )}
    </div>
  );
}
