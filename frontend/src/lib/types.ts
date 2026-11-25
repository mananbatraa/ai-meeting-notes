// Mirrors backend/app/schemas.py. Keep in sync when the API changes.

export type JobStatus = "queued" | "transcribing" | "extracting" | "completed" | "failed";
export type Priority = "low" | "medium" | "high";

export interface Decision {
  decision: string;
  context: string | null;
  timestamp_s: number | null;
}

export interface ActionItem {
  task: string;
  owner: string | null;
  due_date: string | null; // YYYY-MM-DD
  priority: Priority;
  timestamp_s: number | null;
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
