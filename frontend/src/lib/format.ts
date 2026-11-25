import type { ActionItem, JobStatus } from "./types";

export function formatTimestamp(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** "2026-11-27" -> "Fri, Nov 27". Parsed as a local calendar date, not UTC midnight. */
export function formatDate(iso: string): string {
  const [y, mo, d] = iso.split("-").map(Number);
  if (!y || !mo || !d) return iso;
  return new Date(y, mo - 1, d).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export function todayIso(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Queued",
  transcribing: "Transcribing audio",
  extracting: "Writing notes",
  completed: "Done",
  failed: "Failed",
};

const PRIORITY_RANK = { high: 0, medium: 1, low: 2 } as const;

/** Overdue/soonest first, undated last, then by priority. */
export function sortActionItems(items: readonly ActionItem[]): ActionItem[] {
  return [...items].sort((a, b) => {
    if (a.due_date !== b.due_date) {
      if (a.due_date === null) return 1;
      if (b.due_date === null) return -1;
      return a.due_date < b.due_date ? -1 : 1;
    }
    return PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority];
  });
}

export function owners(items: readonly ActionItem[]): string[] {
  return [...new Set(items.map((i) => i.owner).filter((o): o is string => !!o))].sort();
}

export function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot).toLowerCase() : "";
}

export interface FileCheck {
  ok: boolean;
  error?: string;
}

export function checkFile(
  file: File,
  allowed: readonly string[],
  maxMb: number,
): FileCheck {
  const ext = fileExtension(file.name);
  if (!allowed.includes(ext)) {
    return { ok: false, error: `${ext || "This file type"} is not supported. Use ${allowed.join(", ")}.` };
  }
  if (file.size === 0) return { ok: false, error: "The file is empty." };
  if (file.size > maxMb * 1024 * 1024) {
    return { ok: false, error: `The file is larger than ${maxMb} MB.` };
  }
  return { ok: true };
}
