import { api } from "@/lib/api";
import PapersTable from "@/components/PapersTable";

export const dynamic = "force-dynamic";

export default async function PapersPage() {
  const papers = await api.papers();

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-8 border-b border-ink pb-4">
        <h1 className="font-serif text-3xl text-ink">Papers</h1>
        <p className="mt-1 text-graphite">
          {papers.length} paper{papers.length === 1 ? "" : "s"} in the register.
        </p>
      </header>

      <PapersTable papers={papers} />
    </div>
  );
}
