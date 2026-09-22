import type { PaperDetail, PaperSummary, Stats } from "./types";

function baseUrl(): string {
  if (typeof window !== "undefined") return "";

  const url = process.env.BACKEND_URL || "http://localhost:8000";

  console.log("[API] Backend URL:", url);

  return url;
}

async function request<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const url = `${baseUrl()}${path}`;

  console.log("[API] Request:", url);

  try {
    const res = await fetch(url, {
      cache: "no-store",
      ...init,
    });

    if (!res.ok) {
      let detail = res.statusText;

      try {
        const body = await res.json();
        detail = body.detail ?? detail;
      } catch {}

      throw new Error(
        `HTTP ${res.status}: ${detail}`
      );
    }

    return res.json() as Promise<T>;
  } catch (err) {
    console.error("[API] Fetch failed:", url);
    console.error(err);

    throw new Error(
      `Cannot connect to backend at ${url}. Is the backend server running?`
    );
  }
}

export const api = {
  stats: () => request<Stats>("/api/stats"),

  papers: () => request<PaperSummary[]>("/api/papers"),

  paper: (id: number | string) =>
    request<PaperDetail>(`/api/papers/${id}`),

  upload: (file: File) => {
    const form = new FormData();

    form.append("file", file);

    return request<PaperDetail>(
      "/api/upload",
      {
        method: "POST",
        body: form,
      }
    );
  },
};