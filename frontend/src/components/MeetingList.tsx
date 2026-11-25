import { formatDate } from "../lib/format";
import type { MeetingSummary } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

interface Props {
  items: MeetingSummary[];
  selectedId: string | null;
  loading: boolean;
  error: string | null;
  onSelect: (id: string) => void;
}

export function MeetingList({ items, selectedId, loading, error, onSelect }: Props) {
  if (loading) return <p className="muted">Loading meetings…</p>;
  if (error) return <p role="alert" className="error">{error}</p>;
  if (items.length === 0) return <p className="muted">No meetings yet. Upload one to get started.</p>;
  return (
    <ul className="meeting-list">
      {items.map((m) => (
        <li key={m.id}>
          <button
            type="button"
            className={m.id === selectedId ? "meeting-link selected" : "meeting-link"}
            aria-current={m.id === selectedId ? "page" : undefined}
            onClick={() => onSelect(m.id)}
          >
            <span className="meeting-title">{m.title ?? m.filename}</span>
            <span className="meeting-meta">
              {formatDate(m.meeting_date)} <StatusBadge status={m.status} />
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
