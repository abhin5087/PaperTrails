"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/papers", label: "Papers" },
  { href: "/upload", label: "Upload" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-56 flex-none flex-col border-r border-paper-line bg-paper px-6 py-8">
      <div className="mb-10">
        <div className="font-serif text-xl leading-tight text-ink">
          Paper
          <br />
          Trails
        </div>
        <div className="mt-1 text-xs uppercase tracking-wide text-graphite">
          Exam paper register
        </div>
      </div>

      <nav className="flex flex-col gap-1">
        {LINKS.map((link) => {
          const active =
            link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`border-l-2 px-3 py-1.5 text-sm transition-colors ${
                active
                  ? "border-rule text-ink font-medium"
                  : "border-transparent text-graphite hover:text-ink"
              }`}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
