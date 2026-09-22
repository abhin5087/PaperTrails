import type { QuestionOut } from "@/lib/types";

export default function QuestionsTable({ questions }: { questions: QuestionOut[] }) {
  if (questions.length === 0) {
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
          <th className="w-14 py-2 pr-3 font-medium">No.</th>
          <th className="py-2 pr-3 font-medium">Question</th>
          <th className="w-16 py-2 pr-3 font-medium text-right">Marks</th>
          <th className="w-20 py-2 pr-3 font-medium">Module</th>
          <th className="w-16 py-2 pr-3 font-medium">CO</th>
          <th className="w-14 py-2 pr-0 font-medium">BL</th>
        </tr>
      </thead>
      <tbody>
        {questions.map((q) => (
          <tr key={q.id} className="border-b border-paper-line align-top last:border-0">
            <td className="py-3 pr-3 font-medium text-ink tabular-nums">
              {q.question_no}
            </td>
            <td className="py-3 pr-3 text-ink">{q.text || "\u2014"}</td>
            <td className="py-3 pr-3 text-right tabular-nums text-ink">
              {q.marks ?? "\u2014"}
            </td>
            <td className="py-3 pr-3 text-graphite">{q.module ?? "\u2014"}</td>
            <td className="py-3 pr-3 text-graphite">{q.co ?? "\u2014"}</td>
            <td className="py-3 pr-0 text-graphite">{q.bl ?? "\u2014"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
