import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api";
import ConfidenceBadge from "@/components/ConfidenceBadge";
import QuestionsTable from "@/components/QuestionsTable";

export const dynamic = "force-dynamic";

const PDF_TYPE_LABEL: Record<string, string> = {
  vector: "Vector (ruled table)",
  ocr_text: "OCR text (no table)",
  scanned: "Scanned image",
};

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
    ["Semester", paper.semester],
    ["Academic year", paper.academic_year],
    ["Exam type", paper.exam_type],
    ["Slot", paper.slot],
    ["Duration", paper.duration],
    ["Exam date", paper.exam_date],
    ["Max marks", paper.max_marks],
    ["Marks extracted", paper.marks_extracted],
    ["Source", PDF_TYPE_LABEL[paper.pdf_type] ?? paper.pdf_type],
    ["Extraction method", paper.extraction_method],
  ];

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
            <div className="mt-0.5 text-ink">{value ?? "\u2014"}</div>
          </div>
        ))}
      </section>

      {paper.notes.length > 0 && (
        <section className="mb-10 border-l-2 border-stamp/60 bg-stamp/5 px-4 py-3">
          <div className="mb-1 text-xs uppercase tracking-wide text-stamp">
            Extraction notes
          </div>
          <ul className="space-y-1 text-sm text-ink">
            {paper.notes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2 className="mb-3 font-serif text-xl text-ink">
          Questions ({paper.questions.length})
        </h2>
        <QuestionsTable questions={paper.questions} />
      </section>
    </div>
  );
}
