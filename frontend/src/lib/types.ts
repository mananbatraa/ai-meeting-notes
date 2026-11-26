// Mirrors backend/app/schemas.py. Keep in sync when the API changes.

export type JobStatus = "queued" | "transcribing" | "extracting" | "completed" | "failed";
export type Priority = "low" | "medium" | "high";

export interface Decision {
  decision: string;
  context: string | null;
  timestamp_s: number | null;
}

export interface ActionItem {
  id: string;
  task: string;
  owner: string | null;
  due_date: string | null; // YYYY-MM-DD
  priority: Priority;
  timestamp_s: number | null;
  done: boolean;
  edited: boolean; // changed by a person after extraction
}

/** Fields a person can set on an existing item. Omit a field to leave it unchanged. */
export interface ActionItemPatch {
  task?: string;
  owner?: string | null;
  due_date?: string | null;
  priority?: Priority;
  done?: boolean;
}

export interface ActionItemCreate {
  task: string;
  owner: string | null;
  due_date: string | null;
  priority: Priority;
}

export interface MeetingNotes {
  title: string;
  summary: string;
  key_points: string[];
  decisions: Decision[];
  action_items: ActionItem[];
  open_questions: string[];
  participants: string[];
}

export interface Segment {
  start: number;
  end: number;
  text: string;
  speaker: string | null;
}

export interface Transcript {
  language: string | null;
  duration_s: number | null;
  segments: Segment[];
}

export interface MeetingSummary {
  id: string;
  filename: string;
  status: JobStatus;
  title: string | null;
  meeting_date: string;
  created_at: string;
  updated_at: string;
  error: string | null;
}

export interface MeetingDetail extends MeetingSummary {
  transcript: Transcript | null;
  notes: MeetingNotes | null;
}

export interface MeetingList {
  items: MeetingSummary[];
  total: number;
}

export interface PublicConfig {
  max_upload_mb: number;
  audio_extensions: string[];
  transcript_extensions: string[];
  demo_mode: boolean;
}

export const TERMINAL_STATUSES: ReadonlySet<JobStatus> = new Set(["completed", "failed"]);
