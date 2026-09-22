import { api } from "@/lib/api";
import StatCard from "@/components/StatCard";
import PapersTable from "@/components/PapersTable";
import ConfidenceBadge from "@/components/ConfidenceBadge";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const [stats, papers] = await Promise.all([api.stats(), api.papers()]);
  const recent = papers.slice(0, 6);

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-10 border-b border-ink pb-4">
        <h1 className="font-serif text-3xl text-ink">Register overview</h1>
        <p className="mt-1 text-graphite">
          Every paper PaperTrails has read, at a glance.
        </p>
      </header>

      <section className="mb-12 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard label="Total papers" value={stats.total_papers} />
        <StatCard label="Total questions" value={stats.total_questions} />
        <StatCard label="Total courses" value={stats.total_courses} />
      </section>

      <section>
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="font-serif text-xl text-ink">Recently added</h2>
          {papers.length > 0 && (
            <div className="flex items-center gap-2 text-sm text-graphite">
              Average confidence
              <ConfidenceBadge
                value={stats.avg_confidence}
                level={
                  stats.avg_confidence >= 80
                    ? "high"
                    : stats.avg_confidence >= 50
                      ? "medium"
                      : "low"
                }
              />
            </div>
          )}
        </div>
        <PapersTable papers={recent} />
      </section>
    </div>
  );
}
