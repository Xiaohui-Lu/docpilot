import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { FileUp } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { api } from "../lib/api";
import { ErrorNote } from "./ui";

const ACCEPT = ".pdf,.txt,.md";

export function UploadDropzone() {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [lastBatch, setLastBatch] = useState<string[]>([]);

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const names: string[] = [];
      for (const f of files) {
        await api.upload(f);
        names.push(f.name);
      }
      return names;
    },
    onSuccess: (names) => {
      setLastBatch(names);
      void qc.invalidateQueries({ queryKey: ["documents"] });
      void qc.invalidateQueries({ queryKey: ["overview"] });
    },
  });

  const handle = (list: FileList | null) => {
    const files = Array.from(list ?? []);
    if (files.length) upload.mutate(files);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    handle(e.dataTransfer.files);
  };

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={clsx(
          "flex w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-7 text-center transition",
          dragging ? "border-brand-400 bg-brand-50" : "border-line bg-white hover:border-brand-200 hover:bg-paper/60",
        )}
      >
        <div className="grid size-10 place-items-center rounded-full bg-brand-50 text-brand-600">
          <FileUp className="size-5" />
        </div>
        <div className="text-sm font-medium text-ink">
          {upload.isPending ? "Uploading..." : "Drop contracts, invoices or policies here"}
        </div>
        <div className="text-xs text-muted">PDF, TXT or Markdown up to 15 MB - processed in the background</div>
      </button>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple
        className="hidden"
        data-testid="file-input"
        onChange={(e) => {
          handle(e.target.files);
          e.target.value = "";
        }}
      />
      {upload.isError && <ErrorNote error={upload.error} />}
      {upload.isSuccess && lastBatch.length > 0 && (
        <p className="text-xs text-brand-700">
          Queued {lastBatch.length} file{lastBatch.length > 1 ? "s" : ""} for analysis: {lastBatch.join(", ")}
        </p>
      )}
    </div>
  );
}
