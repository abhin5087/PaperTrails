import { AlertTriangle, CircleAlert, HelpCircle, Info } from "lucide-react";
import type { Diagnostic, Severity } from "@/lib/types";

const ORDER: Severity[] = ["error", "warning", "unresolved", "info"];

const STYLES: Record<Severity, { label: string; box: string; icon: typeof Info }> = {
  error: {
    label: "Problems",
    box: "border-stamp/50 bg-stamp/5 text-stamp",
    icon: CircleAlert,
  },
  warning: {
    label: "Check these",
    box: "border-[#946B23]/50 bg-[#946B23]/5 text-[#946B23]",
    icon: AlertTriangle,
  },
  unresolved: {
    label: "Could not be read",
    box: "border-rule/40 bg-rule/5 text-rule",
    icon: HelpCircle,
  },
  info: {
    label: "How this was extracted",
    box: "border-paper-line bg-transparent text-graphite",
    icon: Info,
  },
};

export default function DiagnosticsPanel({
  diagnostics,
}: {
  diagnostics: Diagnostic[];
}) {
  if (!diagnostics || diagnostics.length === 0) return null;

  const groups = ORDER.map((severity) => ({
    severity,
    items: diagnostics.filter((d) => d.severity === severity),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="space-y-3">
      {groups.map(({ severity, items }) => {
        const style = STYLES[severity];
        const Icon = style.icon;

        return (
          <section key={severity} className={`border-l-2 px-4 py-3 ${style.box}`}>
            <div className="mb-1.5 flex items-center gap-1.5 text-xs uppercase tracking-wide">
              <Icon className="h-3.5 w-3.5" />
              {style.label}
              <span className="tabular-nums opacity-70">({items.length})</span>
            </div>
            <ul className="space-y-1 text-sm text-ink">
              {items.map((item) => (
                <li key={`${item.code}-${item.field ?? ""}-${item.message}`}>
                  {item.message}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
