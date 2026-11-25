import type { MeetingDetail, MeetingList, MeetingSummary, PublicConfig } from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

/** FastAPI errors are `{detail: string}` or `{detail: [{msg, loc}]}` for validation. */
function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      return detail
        .map((d: { msg?: string; loc?: unknown[] }) => {
          const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : undefined;
          return field ? `${String(field)}: ${d.msg ?? "invalid"}` : (d.msg ?? "invalid");
        })
        .join("; ");
    }
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError(0, "Could not reach the server. Is the backend running?");
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, errorMessage(body, `Request failed (HTTP ${res.status})`));
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export interface UploadOptions {
  meetingDate?: string;
  title?: string;
}

export const api = {
  config: () => request<PublicConfig>("/api/config"),

  listMeetings: (limit = 20, offset = 0) =>
    request<MeetingList>(`/api/meetings?limit=${limit}&offset=${offset}`),

  getMeeting: (id: string) => request<MeetingDetail>(`/api/meetings/${encodeURIComponent(id)}`),

  uploadMeeting: (file: File, opts: UploadOptions = {}) => {
    const form = new FormData();
    form.append("file", file);
    if (opts.meetingDate) form.append("meeting_date", opts.meetingDate);
    if (opts.title?.trim()) form.append("title", opts.title.trim());
    return request<MeetingSummary>("/api/meetings", { method: "POST", body: form });
  },

  submitTranscript: (text: string, opts: UploadOptions = {}) =>
    request<MeetingSummary>("/api/meetings/transcript", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        title: opts.title?.trim() || null,
        meeting_date: opts.meetingDate || null,
      }),
    }),

  retryMeeting: (id: string) =>
    request<MeetingSummary>(`/api/meetings/${encodeURIComponent(id)}/retry`, { method: "POST" }),

  deleteMeeting: (id: string) =>
    request<void>(`/api/meetings/${encodeURIComponent(id)}`, { method: "DELETE" }),

  markdown: (id: string) => request<string>(`/api/meetings/${encodeURIComponent(id)}/markdown`),
};
