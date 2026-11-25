import { useEffect, useState } from "react";

import { useMeeting } from "../hooks/useMeeting";
import { api } from "../lib/api";
import { formatDate, formatTimestamp } from "../lib/format";
import { TERMINAL_STATUSES } from "../lib/types";
import { ActionItemsTable } from "./ActionItemsTable";
import { ProgressSteps, StatusBadge } from "./StatusBadge";
import { segmentAt, TranscriptView } from "./TranscriptView";

interface Props {
  id: string;
  onChanged: () => unknown;
  onDeleted: () => void;
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function MeetingView({ id, onChanged, onDeleted }: Props) {
  const { meeting, error, notFound, refresh } = useMeeting(id);
  const [seek, setSeek] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const status = meeting?.status;

  // keep the sidebar's status badges in step with what this page sees
  useEffect(() => {
    if (status) onChanged();
  }, [status, onChanged]);

  if (notFound) return <p className="card">This meeting no longer exists.</p>;
  if (!meeting) return error ? <p role="alert" className="error">{error}</p> : <p className="muted">Loading…</p>;

  const run = async (fn: () => Promise<void>) => {
    setActionError(null);
    try {
      await fn();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    }
  };

  const jumpTo = (seconds: number) => {
    setSeek(seconds);
    if (meeting.transcript) {
      document.getElementById(`seg-${segmentAt(meeting.transcript, seconds)}`)?.scrollIntoView?.({
        behavior: "smooth",
        block: "center",
      });
    }
  };

  const notes = meeting.notes;
  return (
    <article className="meeting">
      <header className="meeting-header">
        <div>
          <h2>{meeting.title ?? notes?.title ?? meeting.filename}</h2>
          <p className="muted">
            {formatDate(meeting.meeting_date)} · {meeting.filename} <StatusBadge status={meeting.status} />
          </p>
        </div>
        <div className="actions-bar">
          {notes && (
            <>
              <button
                type="button"
                onClick={() =>
                  run(async () => {
                    await navigator.clipboard.writeText(await api.markdown(id));
                    setCopied(true);
                  })
                }
              >
                {copied ? "Copied" : "Copy Markdown"}
              </button>
              <button
                type="button"
                onClick={() => run(async () => download(`meeting-${id.slice(0, 8)}.md`, await api.markdown(id)))}
              >
                Download .md
              </button>
            </>
          )}
          {TERMINAL_STATUSES.has(meeting.status) && (
            <button
              type="button"
              className="danger"
              onClick={() =>
                run(async () => {
                  await api.deleteMeeting(id);
                  onDeleted();
                })
              }
            >
              Delete
            </button>
          )}
        </div>
      </header>

      {actionError && (
        <p role="alert" className="error">
          {actionError}
        </p>
      )}
      {error && <p className="muted small">Connection problem, retrying: {error}</p>}

      {!TERMINAL_STATUSES.has(meeting.status) && (
        <section className="card">
          <ProgressSteps status={meeting.status} />
          <p className="muted">Long recordings take a few minutes to transcribe. This page updates by itself.</p>
        </section>
      )}

      {meeting.status === "failed" && (
        <section className="card failed" role="alert">
          <h3>Processing failed</h3>
          <p>{meeting.error ?? "Unknown error"}</p>
          <button
            type="button"
            className="primary"
            onClick={() =>
              run(async () => {
                await api.retryMeeting(id);
                refresh();
                onChanged();
              })
            }
          >
            Retry
          </button>
        </section>
      )}

      {notes && (
        <>
          <section className="card">
            <h3>Summary</h3>
            <p>{notes.summary}</p>
            {notes.participants.length > 0 && (
              <p className="muted small">With {notes.participants.join(", ")}</p>
            )}
            {notes.key_points.length > 0 && (
              <ul>
                {notes.key_points.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            )}
          </section>

          <section className="card">
            <h3>Action items</h3>
            <ActionItemsTable
              items={notes.action_items}
              meetingDate={meeting.meeting_date}
              onSeek={meeting.transcript ? jumpTo : undefined}
            />
          </section>

          <section className="card">
            <h3>Decisions</h3>
            {notes.decisions.length === 0 ? (
              <p className="muted">No decisions were recorded.</p>
            ) : (
              <ul className="decisions">
                {notes.decisions.map((d, i) => (
                  <li key={i}>
                    <span>{d.decision}</span>
                    {d.timestamp_s !== null && meeting.transcript && (
                      <button type="button" className="ts" onClick={() => jumpTo(d.timestamp_s as number)}>
                        {formatTimestamp(d.timestamp_s)}
                      </button>
                    )}
                    {d.context && <p className="muted small">{d.context}</p>}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {notes.open_questions.length > 0 && (
            <section className="card">
              <h3>Open questions</h3>
              <ul>
                {notes.open_questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}

      {meeting.transcript && (
        <details className="card" open={seek !== null}>
          <summary>
            <h3>Transcript</h3>
          </summary>
          <TranscriptView transcript={meeting.transcript} highlight={seek} />
        </details>
      )}
    </article>
  );
}
