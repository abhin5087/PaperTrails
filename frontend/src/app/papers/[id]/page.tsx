import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import DiagnosticsPanel from "@/components/DiagnosticsPanel";
import FigureGallery from "@/components/FigureGallery";
import QuestionsTable from "@/components/QuestionsTable";

export const dynamic = "force-dynamic";

const PDF_TYPE_LABEL: Record<string, string> = {
  vector: "Vector (ruled table)",
  ocr_text: "Text layer (no table)",
  scanned: "Scanned image",
};

/** How the text was obtained, in plain words. */
function sourceLabel(paper: {
  ocr_engine: string | null;
  ocr_config: string | null;
  ocr_confidence: number | null;
}): string {
  if (!paper.ocr_engine) return "PDF text layer";

  const parts = [`OCR (${paper.ocr_engine}`];
  if (paper.ocr_config) parts.push(`, ${paper.ocr_config}`);
  parts.push(")");
  if (paper.ocr_confidence !== null) {
    parts.push(` · ${Math.round(paper.ocr_confidence)}% confidence`);
  }
  return parts.join("");
}

export default async function PaperDetailPage({
  params,
}: {
  params: { id: string };
}) {
  let paper;
  try {
    paper = await api.paper(params.id);
  } catch {
    notFound();
  }

  const metaRows: [string, string | number | null][] = [
    ["Course", paper.course_code],
    ["Course name", paper.course_name],
    ["Semester", paper.semester],
    ["Academic year", paper.academic_year],
    ["Exam type", paper.exam_type],
    ["Slot", paper.slot],
    ["Duration", paper.duration],
    ["Exam date", paper.exam_date],
    ["Exam time", paper.exam_time],
    ["Max marks", paper.max_marks],
    ["Marks extracted", paper.marks_extracted],
    ["Pages", paper.page_count || null],
    ["Source", PDF_TYPE_LABEL[paper.pdf_type] ?? paper.pdf_type],
    ["Read with", sourceLabel(paper)],
  ];

  const topLevel = paper.questions.filter((q) => !q.parent_no).length;
  const unresolved = paper.questions.filter(
    (q) => q.marks === null && q.marks_raw !== null,
  ).length;

  return (
    <div className="mx-auto max-w-5xl">
      <Link
        href="/papers"
        className="mb-6 inline-flex items-center gap-1.5 text-sm text-graphite hover:text-ink"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to papers
      </Link>

      <header className="mb-8 flex items-start justify-between border-b border-ink pb-4">
        <div>
          <h1 className="font-serif text-3xl text-ink">{paper.course_code}</h1>
          <p className="mt-1 text-graphite">{paper.original_filename}</p>
        </div>
        <ConfidenceBadge value={paper.confidence} level={paper.confidence_level} />
      </header>

      <section className="mb-10 grid grid-cols-2 gap-x-8 gap-y-3 border border-paper-line px-6 py-5 sm:grid-cols-3">
        {metaRows.map(([label, value]) => (
          <div key={label}>
            <div className="text-xs uppercase tracking-wide text-graphite">
              {label}
            </div>
            <div className="mt-0.5 text-ink">{value ?? "—"}</div>
          </div>
        ))}
      </section>

      {paper.diagnostics.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-3 font-serif text-xl text-ink">Extraction report</h2>
          <DiagnosticsPanel diagnostics={paper.diagnostics} />
        </section>
      )}

      <section className="mb-10">
        <h2 className="mb-3 font-serif text-xl text-ink">
          Questions ({topLevel})
          {unresolved > 0 && (
            <span className="ml-2 text-sm font-normal text-stamp">
              {unresolved} with unresolved marks
            </span>
          )}
        </h2>
        <QuestionsTable questions={paper.questions} />
      </section>

      {paper.figures.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-3 font-serif text-xl text-ink">
            Figures ({paper.figures.length})
          </h2>
          <FigureGallery figures={paper.figures} />
        </section>
      )}
    </div>
  );
}
