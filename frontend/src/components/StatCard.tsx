export default function StatCard({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="border border-paper-line bg-paper px-5 py-4">
      <div className="font-serif text-3xl text-ink tabular-nums">{value}</div>
      <div className="mt-1 text-sm text-graphite">{label}</div>
    </div>
  );
}
