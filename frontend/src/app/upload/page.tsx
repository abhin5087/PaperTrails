"use client";

import { useState } from "react";
import Link from "next/link";
import UploadDropzone from "@/components/UploadDropzone";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import QuestionsTable from "@/components/QuestionsTable";
import type { PaperDetail } from "@/lib/types";

export default function UploadPage() {
  const [result, setResult] = useState<PaperDetail | null>(null);

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-8 border-b border-ink pb-4">
        <h1 className="font-serif text-3xl text-ink">Upload a paper</h1>
        <p className="mt-1 text-graphite">
          PaperTrails will detect the layout, extract every question, and
          score how much it trusts the result.
        </p>
      </header>

      {!result ? (
        <UploadDropzone onDone={setResult} />
      ) : (
        <div>
          <div className="mb-8 flex items-start justify-between border border-paper-line px-6 py-5">
            <div>
              <div className="font-serif text-xl text-ink">
                {result.course_code}
                <span className="ml-2 text-base font-normal text-graphite">
                  {result.original_filename}
                </span>
              </div>
              <div className="mt-1 text-sm text-graphite">
                {result.question_count} question
                {result.question_count === 1 ? "" : "s"} extracted &middot;{" "}
                {result.exam_type ?? "exam type unknown"}
              </div>
            </div>
            <ConfidenceBadge value={result.confidence} level={result.confidence_level} />
          </div>

          {result.notes.length > 0 && (
            <div className="mb-8 border-l-2 border-stamp/60 bg-stamp/5 px-4 py-3">
              <div className="mb-1 text-xs uppercase tracking-wide text-stamp">
                Extraction notes
              </div>
              <ul className="space-y-1 text-sm text-ink">
                {result.notes.map((note, i) => (
                  <li key={i}>{note}</li>
                ))}
              </ul>
            </div>
          )}

          <QuestionsTable questions={result.questions} />

          <div className="mt-8 flex gap-4 text-sm">
            <Link href={`/papers/${result.id}`} className="text-rule hover:underline">
              View full paper page
            </Link>
            <button
              onClick={() => setResult(null)}
              className="text-graphite hover:text-ink"
            >
              Upload another
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
