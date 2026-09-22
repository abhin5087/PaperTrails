import type { Metadata } from "next";
import { Source_Serif_4, IBM_Plex_Sans } from "next/font/google";
import Sidebar from "@/components/Sidebar";
import "./globals.css";

const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-source-serif",
  display: "swap",
});

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "PaperTrails",
  description: "A register of extracted exam papers and their questions.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${sourceSerif.variable} ${plexSans.variable}`}>
      <body className="flex min-h-screen font-sans text-ink antialiased">
        <Sidebar />
        <main className="flex-1 overflow-y-auto px-10 py-10">{children}</main>
      </body>
    </html>
  );
}
