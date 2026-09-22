"use client";

import Link from "next/link";
import type { PaperSummary } from "@/lib/types";
import ConfidenceBadge from "./ConfidenceBadge";

const PDF_TYPE_LABEL: Record<PaperSummary["pdf_type"], string> = {
  vector: "Vector",
  ocr_text: "OCR text",
  scanned: "Scanned",
};

export default function PapersTable({ papers }: { papers: PaperSummary[] }) {
  if (papers.length === 0) {
    return (
      <div className="border border-dashed border-paper-line px-6 py-12 text-center text-graphite">
        No papers yet. Upload one to start the register.
      </div>
    );
  }

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-ink text-left text-xs uppercase tracking-wide text-graphite">
          <th className="py-2 pr-4 font-medium">Course</th>
          <th className="py-2 pr-4 font-medium">Semester</th>
          <th className="py-2 pr-4 font-medium">Exam type</th>
          <th className="py-2 pr-4 font-medium">Source</th>
          <th className="py-2 pr-4 font-medium text-right">Questions</th>
          <th className="py-2 pr-0 font-medium text-right">Confidence</th>
        </tr>
      </thead>
      <tbody>
        {papers.map((p) => (
          <tr
            key={p.id}
            className="border-b border-paper-line last:border-0 hover:bg-white/50"
          >
            <td className="py-3 pr-4">
              <Link href={`/papers/${p.id}`} className="text-rule hover:underline">
                {p.course_code}
              </Link>
              {p.course_name && (
                <div className="text-xs text-graphite">{p.course_name}</div>
              )}
            </td>
            <td className="py-3 pr-4 text-ink">{p.semester ?? "\u2014"}</td>
            <td className="py-3 pr-4 text-ink">{p.exam_type ?? "\u2014"}</td>
            <td className="py-3 pr-4 text-graphite">{PDF_TYPE_LABEL[p.pdf_type]}</td>
            <td className="py-3 pr-4 text-right tabular-nums text-ink">
              {p.question_count}
            </td>
            <td className="py-3 pr-0 text-right">
              <ConfidenceBadge value={p.confidence} level={p.confidence_level} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
