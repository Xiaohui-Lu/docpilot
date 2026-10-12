import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronRight, Download, FileSearch, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { UploadDropzone } from "../components/UploadDropzone";
import { Card, Empty, ErrorNote, PageHeader, RiskBadge, Spinner, StatusBadge, TypeTag } from "../components/ui";
import { api, type DocumentFilters } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatBytes, timeAgo } from "../lib/format";

export function DocumentsPage() {
  const { can } = useAuth();
  const [filters, setFilters] = useState<DocumentFilters>({ page: 1 });
  const [exporting, setExporting] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["documents", filters],
    queryFn: () => api.documents(filters),
    placeholderData: keepPreviousData,
    refetchInterval: (q) =>
      q.state.data?.items.some((d) => d.status === "queued" || d.status === "processing") ? 1500 : false,
  });

  const set = (patch: DocumentFilters) => setFilters((f) => ({ ...f, ...patch, page: patch.page ?? 1 }));

  const exportCsv = async () => {
    setExporting(true);
    try {
      const blob = await api.exportCsv();
      const url = URL.createObjectURL(blob);
      const a = Object.assign(document.createElement("a"), { href: url, download: "docpilot-insights.csv" });
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <>
      <PageHeader kicker="Library" title="Documents">
        <button className="btn-secondary" onClick={exportCsv} disabled={exporting} type="button">
          <Download className="size-4" /> Export CSV
        </button>
      </PageHeader>

      {can("member") && (
        <div className="mb-5">
          <UploadDropzone />
        </div>
      )}

      <Card bodyClassName="p-0">
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" />
            <input
              className="input pl-9"
              placeholder="Search by title or filename"
              aria-label="Search documents"
              value={filters.q ?? ""}
              onChange={(e) => set({ q: e.target.value })}
            />
          </div>
          <select
            className="input w-auto"
            aria-label="Type"
            value={filters.doc_type ?? ""}
            onChange={(e) => set({ doc_type: e.target.value })}
          >
            <option value="">All types</option>
            <option value="contract">Contracts</option>
            <option value="nda">NDAs</option>
            <option value="invoice">Invoices</option>
            <option value="policy">Policies</option>
            <option value="other">Other</option>
          </select>
          <select
            className="input w-auto"
            aria-label="Risk"
            value={filters.risk ?? ""}
            onChange={(e) => set({ risk: e.target.value })}
          >
            <option value="">Any risk</option>
            <option value="high">High risk</option>
            <option value="medium">Medium risk</option>
            <option value="low">Low risk</option>
          </select>
          <select
            className="input w-auto"
            aria-label="Status"
            value={filters.status ?? ""}
            onChange={(e) => set({ status: e.target.value })}
          >
            <option value="">Any status</option>
            <option value="ready">Ready</option>
            <option value="queued">Queued</option>
            <option value="processing">Processing</option>
            <option value="failed">Failed</option>
          </select>
          <select
            className="input w-auto"
            aria-label="Rulebook"
            value={filters.policy ?? ""}
            onChange={(e) => set({ policy: e.target.value })}
          >
            <option value="">Any rulebook result</option>
            <option value="violations">Breaks a rule</option>
            <option value="compliant">Compliant</option>
          </select>
        </div>

        {error && (
          <div className="p-4">
            <ErrorNote error={error} />
          </div>
        )}
        {isLoading ? (
          <Spinner />
        ) : !data || data.items.length === 0 ? (
          <Empty icon={<FileSearch className="size-8" />} title="No documents match">
            Try a different search or upload a file.
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-paper/60 text-left text-xs text-muted">
                <tr>
                  <th className="px-5 py-2.5 font-medium">Document</th>
                  <th className="px-3 py-2.5 font-medium">Type</th>
                  <th className="px-3 py-2.5 font-medium">Risk</th>
                  <th className="px-3 py-2.5 font-medium">Rulebook</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="px-3 py-2.5 font-medium">Uploaded</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.items.map((d) => (
                  <tr key={d.id} className="group hover:bg-paper/40">
                    <td className="max-w-[420px] px-5 py-3">
                      <Link to={`/documents/${d.id}`} className="block">
                        <div className="truncate font-medium text-ink group-hover:text-brand-700">
                          {d.title ?? d.filename}
                        </div>
                        <div className="truncate text-xs text-muted">
                          {d.filename} · {formatBytes(d.size_bytes)}
                        </div>
                      </Link>
                      {d.status === "failed" && d.error && (
                        <div className="mt-1 truncate text-xs text-red-700">{d.error}</div>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <TypeTag type={d.doc_type} />
                    </td>
                    <td className="px-3 py-3">
                      <RiskBadge level={d.overall_risk} />
                    </td>
                    <td className="px-3 py-3">
                      {d.status !== "ready" ? (
                        <span className="text-xs text-muted">-</span>
                      ) : d.policy_violations ? (
                        <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700">
                          {d.policy_violations} issue{d.policy_violations > 1 ? "s" : ""}
                        </span>
                      ) : (
                        <span className="text-xs font-medium text-brand-700">Compliant</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge status={d.status} />
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-muted">{timeAgo(d.created_at)}</td>
                    <td className="pr-4">
                      <Link to={`/documents/${d.id}`} aria-label={`Open ${d.title ?? d.filename}`}>
                        <ChevronRight className="size-4 text-muted group-hover:text-ink" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > data.page_size && (
          <div className="flex items-center justify-between border-t border-line px-5 py-3 text-sm text-muted">
            <span>{data.total} documents</span>
            <div className="flex items-center gap-2">
              <button
                className="btn-secondary py-1"
                disabled={data.page <= 1}
                type="button"
                onClick={() => set({ page: data.page - 1 })}
              >
                Previous
              </button>
              <span>
                Page {data.page} of {pages}
              </span>
              <button
                className="btn-secondary py-1"
                disabled={data.page >= pages}
                type="button"
                onClick={() => set({ page: data.page + 1 })}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}
