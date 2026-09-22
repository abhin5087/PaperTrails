import type { ConfidenceLevel } from "@/lib/types";

const STYLES: Record<ConfidenceLevel, string> = {
  high: "border-register text-register",
  medium: "border-[#946B23] text-[#946B23]",
  low: "border-stamp text-stamp",
};

const LABELS: Record<ConfidenceLevel, string> = {
  high: "Reliable",
  medium: "Review",
  low: "Low",
};

export default function ConfidenceBadge({
  value,
  level,
}: {
  value: number;
  level: ConfidenceLevel;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-xs font-medium tabular-nums ${STYLES[level]}`}
      title={LABELS[level]}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          level === "high"
            ? "bg-register"
            : level === "medium"
              ? "bg-[#946B23]"
              : "bg-stamp"
        }`}
      />
      {value}%
    </span>
  );
}
