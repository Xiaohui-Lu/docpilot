import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { AnswerView, AskBox } from "../components/AskBox";
import { Card, Empty, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { timeAgo } from "../lib/format";

const SUGGESTIONS = [
  "Which contracts renew automatically, and what notice is required?",
  "When is the CloudPeak invoice due?",
  "What are the security incident notification timelines?",
  "Who owns the intellectual property in the consulting agreement?",
];

export function AskPage() {
  const { data: history } = useQuery({ queryKey: ["history"], queryFn: () => api.history() });

  return (
    <>
      <PageHeader kicker="Retrieval-augmented Q&A" title="Ask across all documents" />
      <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <AskBox placeholder="Ask anything about your contracts, invoices and policies..." suggestions={SUGGESTIONS} />
          <p className="mt-4 text-xs text-muted">
            Answers are generated only from your organization's documents. Each statement links to the passage it came
            from, so you can verify it in one click.
          </p>
        </Card>
        <Card
          title={
            <span className="flex items-center gap-2">
              <History className="size-4" /> Recent questions
            </span>
          }
          bodyClassName="p-0"
        >
          {!history?.length ? (
            <Empty title="No questions yet">Questions your team asks will appear here.</Empty>
          ) : (
            <ul className="max-h-[640px] divide-y divide-line overflow-y-auto">
              {history.map((h) => (
                <li key={h.id} className="px-5 py-4">
                  <div className="mb-2 flex items-start justify-between gap-3">
                    <div className="text-sm font-semibold">{h.question}</div>
                    <span className="shrink-0 text-[11px] text-muted">{timeAgo(h.created_at)}</span>
                  </div>
                  <AnswerView answer={h.answer} citations={h.citations.slice(0, 2)} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
