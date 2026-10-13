import type { QuestionOut } from "@/lib/types";

/** What to show in the marks column.
 *
 * A resolved mark is the number.  An unresolved one shows the raw text the
 * paper printed, marked as unread rather than silently blank - the point is
 * that the value exists but could not be trusted. */
function Marks({ question }: { question: QuestionOut }) {
  if (question.marks !== null) {
    const split = question.marks_parts.length > 1;
    return (
      <span className="tabular-nums text-ink" title={split ? question.marks_raw ?? "" : undefined}>
        {question.marks}
        {split && (
          <span className="ml-1 text-xs text-graphite">({question.marks_raw})</span>
        )}
      </span>
    );
  }

  if (question.marks_raw) {
    return (
      <span
        className="cursor-help border-b border-dotted border-stamp text-stamp"
        title={question.marks_reason ?? "Could not be read with confidence"}
      >
        {question.marks_raw}?
      </span>
    );
  }

  return <span className="text-graphite">{"—"}</span>;
}

export default function QuestionsTable({ questions }: { questions: QuestionOut[] }) {
  if (!questions || questions.length === 0) {
    return (
      <div className="border border-dashed border-paper-line px-6 py-10 text-center text-graphite">
        No questions were extracted from this paper.
      </div>
    );
  }

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-ink text-left text-xs uppercase tracking-wide text-graphite">
          <th className="w-20 py-2 pr-3 font-medium">No.</th>
          <th className="py-2 pr-3 font-medium">Question</th>
          <th className="w-24 py-2 pr-3 font-medium text-right">Marks</th>
          <th className="w-20 py-2 pr-3 font-medium">Module</th>
          <th className="w-16 py-2 pr-3 font-medium">CO</th>
          <th className="w-14 py-2 pr-0 font-medium">BL</th>
        </tr>
      </thead>
      <tbody>
        {questions.map((q) => {
          const isChild = Boolean(q.parent_no);

          return (
            <tr
              key={q.id}
              className={`border-b border-paper-line align-top last:border-0 ${
                isChild ? "bg-paper-line/10" : ""
              }`}
            >
              <td
                className={`py-3 pr-3 tabular-nums ${
                  isChild ? "pl-5 text-graphite" : "font-medium text-ink"
                }`}
              >
                {q.question_no}
                {q.recovered_label && (
                  <span
                    className="ml-1 cursor-help text-xs text-stamp"
                    title="This label was reconstructed from damaged text - check the numbering"
                  >
                    *
                  </span>
                )}
              </td>
              <td className={`py-3 pr-3 ${isChild ? "text-graphite" : "text-ink"}`}>
                {q.text || "—"}
              </td>
              <td className="py-3 pr-3 text-right">
                <Marks question={q} />
              </td>
              <td className="py-3 pr-3 text-graphite">{q.module ?? "—"}</td>
              <td className="py-3 pr-3 text-graphite">{q.co ?? "—"}</td>
              <td className="py-3 pr-0 text-graphite">{q.bl ?? "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
