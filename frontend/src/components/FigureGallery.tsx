import type { FigureOut } from "@/lib/types";

const KIND_LABEL: Record<string, string> = {
  vector: "Drawn diagram",
  image: "Embedded image",
  ink: "Detected region",
};

function FigureCard({ figure, index, total, apiBase }: {
  figure: FigureOut;
  index: number;
  total: number;
  apiBase: string;
}) {
  return (
    <figure className="border border-paper-line">
      {figure.image_url ? (
        // Served by the backend from the saved crop.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`${apiBase}${figure.image_url}`}
          alt={figure.caption ?? `Figure on page ${figure.page}`}
          className="w-full bg-white object-contain"
        />
      ) : (
        <div className="px-4 py-8 text-center text-sm text-graphite">
          No image could be produced for this region.
          {figure.note && <div className="mt-1 text-xs">{figure.note}</div>}
        </div>
      )}

      <figcaption className="border-t border-paper-line px-3 py-2 text-xs text-graphite">
        {figure.caption && (
          <div className="mb-0.5 not-italic text-ink">{figure.caption}</div>
        )}
        {total > 1 && <span className="text-ink">{index + 1} of {total} &middot; </span>}
        page {figure.page}
        {" \u00b7 "}
        {KIND_LABEL[figure.kind] ?? figure.kind}
        {/* An ink region is inferred from pixels, so say it is approximate
            rather than implying the bounds are exact. */}
        {figure.kind === "ink" && (
          <span
            className="ml-1 cursor-help border-b border-dotted border-graphite"
            title={figure.note ?? "Region inferred from the page image"}
          >
            approximate
          </span>
        )}
        {figure.clipped_edges.length > 0 && (
          <span
            className="ml-1 cursor-help text-stamp"
            title={`Content reaches the ${figure.clipped_edges.join(", ")} edge, so the figure may continue past it`}
          >
            may be cut off
          </span>
        )}
      </figcaption>
    </figure>
  );
}

export default function FigureGallery({
  figures,
  apiBase = "",
}: {
  figures: FigureOut[];
  apiBase?: string;
}) {
  if (!figures || figures.length === 0) return null;

  // Group by the question each figure belongs to, keeping document order
  // within a group.  Grouping is presentation only - the API already returns
  // one entry per finalised figure, so nothing is hidden here.
  const order: (string | null)[] = [];
  const groups = new Map<string | null, FigureOut[]>();

  for (const figure of figures) {
    const key = figure.question_no ?? null;
    if (!groups.has(key)) {
      groups.set(key, []);
      order.push(key);
    }
    groups.get(key)!.push(figure);
  }

  return (
    <div className="space-y-8">
      {order.map((key) => {
        const group = groups.get(key)!;
        return (
          <section key={key ?? "unattributed"}>
            <h3 className="mb-2 text-xs uppercase tracking-wide text-graphite">
              {key ? `Question ${key}` : "Not attributed to a question"}
              {group.length > 1 && (
                <span className="ml-1.5 tabular-nums">({group.length} figures)</span>
              )}
            </h3>
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
              {group.map((figure, index) => (
                <FigureCard
                  key={figure.id}
                  figure={figure}
                  index={index}
                  total={group.length}
                  apiBase={apiBase}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
