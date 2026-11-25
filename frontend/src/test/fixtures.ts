import type { MeetingDetail, MeetingNotes, PublicConfig, Transcript } from "../lib/types";

export const config: PublicConfig = {
  max_upload_mb: 1,
  audio_extensions: [".m4a", ".mp3", ".wav"],
  transcript_extensions: [".srt", ".txt", ".vtt"],
  demo_mode: false,
};

export const transcript: Transcript = {
  language: "en",
  duration_s: 60,
  segments: [
    { start: 0, end: 15, speaker: "Priya", text: "Let's start the launch sync." },
    { start: 15, end: 40, speaker: "Sam", text: "I'll finish the SDK upgrade by Friday." },
    { start: 40, end: 60, speaker: "Lee", text: "We agreed to launch on the 10th." },
  ],
};

export const notes: MeetingNotes = {
  title: "Launch sync",
  summary: "The team moved the launch to the 10th.",
  key_points: ["Android blocked on SDK"],
  decisions: [{ decision: "Launch on the 10th", context: "Need beta feedback", timestamp_s: 40 }],
  action_items: [
    { task: "Write launch brief", owner: "Lee", due_date: null, priority: "low", timestamp_s: null },
    { task: "Finish SDK upgrade", owner: "Sam", due_date: "2026-11-27", priority: "high", timestamp_s: 15 },
    { task: "Set up crash alerts", owner: null, due_date: "2026-11-30", priority: "medium", timestamp_s: 50 },
  ],
  open_questions: ["Do we need the press kit?"],
  participants: ["Priya", "Sam", "Lee"],
};

export function meeting(overrides: Partial<MeetingDetail> = {}): MeetingDetail {
  return {
    id: "m-1",
    filename: "sync.mp3",
    status: "completed",
    title: null,
    meeting_date: "2026-11-25",
    created_at: "2026-11-25T18:00:00Z",
    updated_at: "2026-11-25T18:01:00Z",
    error: null,
    transcript,
    notes,
    ...overrides,
  };
}

type Handler = (init?: RequestInit) => { status?: number; body?: unknown } | Promise<{ status?: number; body?: unknown }>;

/** Install a fetch mock keyed by "METHOD path" (query string ignored unless included in the key). */
export function mockFetch(routes: Record<string, Handler>) {
  const calls: { method: string; url: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ method, url, init });
    const path = url.split("?")[0];
    const handler = routes[`${method} ${url}`] ?? routes[`${method} ${path}`];
    if (!handler) return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    const { status = 200, body } = await handler(init);
    if (status === 204) return new Response(null, { status });
    const isText = typeof body === "string";
    return new Response(isText ? body : JSON.stringify(body), {
      status,
      headers: { "content-type": isText ? "text/markdown" : "application/json" },
    });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}
