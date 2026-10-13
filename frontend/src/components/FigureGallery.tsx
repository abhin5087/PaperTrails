import type { FigureOut } from "@/lib/types";

const KIND_LABEL: Record<string, string> = {
  vector: "Drawn diagram",
  image: "Embedded image",
  ink: "Detected region",
};

export default function FigureGallery({
  figures,
  apiBase = "",
}: {
  figures: FigureOut[];
  apiBase?: string;
}) {
  if (!figures || figures.length === 0) return null;

  return (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
      {figures.map((figure) => (
        <figure key={figure.id} className="border border-paper-line">
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
            <span className="text-ink">
              {figure.question_no ? `Question ${figure.question_no}` : "Unattributed"}
            </span>
            {" · "}
            page {figure.page}
            {" · "}
            {KIND_LABEL[figure.kind] ?? figure.kind}
            {figure.caption && (
              <div className="mt-1 italic text-ink">{figure.caption}</div>
            )}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
