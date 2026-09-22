"use client";

import { useCallback, useRef, useState } from "react";
import { UploadCloud, FileText, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { PaperDetail } from "@/lib/types";

export default function UploadDropzone({
  onDone,
}: {
  onDone: (paper: PaperDetail) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    async (file: File) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setError("Only PDF files are accepted.");
        return;
      }
      setError(null);
      setBusy(true);
      try {
        const paper = await api.upload(file);
        onDone(paper);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed.");
      } finally {
        setBusy(false);
      }
    },
    [onDone],
  );

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files?.[0];
          if (file) handleFile(file);
        }}
        onClick={() => !busy && inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center border-2 border-dashed px-6 py-16 text-center transition-colors ${
          dragging ? "border-rule bg-rule/5" : "border-paper-line"
        } ${busy ? "cursor-wait opacity-70" : ""}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleFile(file);
          }}
        />
        {busy ? (
          <>
            <Loader2 className="mb-4 h-8 w-8 animate-spin text-rule" />
            <p className="text-ink">Reading the paper…</p>
            <p className="mt-1 text-sm text-graphite">
              Detecting layout and extracting questions
            </p>
          </>
        ) : (
          <>
            <UploadCloud className="mb-4 h-8 w-8 text-rule-light" />
            <p className="text-ink">Drop a PDF here, or click to choose one</p>
            <p className="mt-1 text-sm text-graphite">
              VIT exam papers — vector, OCR-text, or scanned
            </p>
          </>
        )}
      </div>

      {error && (
        <div className="mt-4 flex items-start gap-2 border border-stamp/40 bg-stamp/5 px-4 py-3 text-sm text-stamp">
          <FileText className="mt-0.5 h-4 w-4 flex-none" />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
}
