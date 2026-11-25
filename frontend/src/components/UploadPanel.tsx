import { useId, useState, type DragEvent, type FormEvent } from "react";

import { api } from "../lib/api";
import { checkFile, todayIso } from "../lib/format";
import type { MeetingSummary, PublicConfig } from "../lib/types";

interface Props {
  config: PublicConfig | null;
  onCreated: (meeting: MeetingSummary) => void;
}

type Mode = "file" | "paste";

export function UploadPanel({ config, onCreated }: Props) {
  const [mode, setMode] = useState<Mode>("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [meetingDate, setMeetingDate] = useState(todayIso());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const ids = { file: useId(), title: useId(), date: useId(), text: useId() };

  const allowed = config ? [...config.audio_extensions, ...config.transcript_extensions] : [];

  const pick = (f: File | null | undefined) => {
    setError(null);
    if (!f) return setFile(null);
    if (config) {
      const check = checkFile(f, allowed, config.max_upload_mb);
      if (!check.ok) {
        setFile(null);
        return setError(check.error ?? "Invalid file");
      }
    }
    setFile(f);
  };

  const onDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setDragging(false);
    pick(e.dataTransfer.files[0]);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const opts = { title, meetingDate };
    if (mode === "file" && !file) return setError("Choose a recording or transcript file.");
    if (mode === "paste" && !text.trim()) return setError("Paste the transcript text.");
    setBusy(true);
    try {
      const created =
        mode === "file" && file ? await api.uploadMeeting(file, opts) : await api.submitTranscript(text, opts);
      setFile(null);
      setText("");
      setTitle("");
      onCreated(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card upload" onSubmit={submit} aria-label="New meeting">
      <h2>New meeting</h2>
      <div className="tabs" role="tablist">
        <button type="button" role="tab" aria-selected={mode === "file"} onClick={() => setMode("file")}>
          Upload file
        </button>
        <button type="button" role="tab" aria-selected={mode === "paste"} onClick={() => setMode("paste")}>
          Paste transcript
        </button>
      </div>

      {mode === "file" ? (
        <label
          htmlFor={ids.file}
          className={dragging ? "dropzone dragging" : "dropzone"}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <span>{file ? file.name : "Drop a recording here or click to choose"}</span>
          <small className="muted">
            Audio or video{config ? ` up to ${config.max_upload_mb} MB` : ""}, or a .txt / .vtt / .srt
            transcript
          </small>
          <input
            id={ids.file}
            type="file"
            className="visually-hidden"
            accept={allowed.join(",") || undefined}
            onChange={(e) => pick(e.target.files?.[0])}
            aria-label="Meeting file"
          />
        </label>
      ) : (
        <div className="field">
          <label htmlFor={ids.text}>Transcript</label>
          <textarea
            id={ids.text}
            rows={8}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"Priya: Let's start.\nSam: I'll finish the SDK upgrade by Friday."}
          />
        </div>
      )}

      <div className="row">
        <div className="field">
          <label htmlFor={ids.title}>Title (optional)</label>
          <input id={ids.title} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor={ids.date}>Meeting date</label>
          <input
            id={ids.date}
            type="date"
            value={meetingDate}
            required
            onChange={(e) => setMeetingDate(e.target.value)}
          />
        </div>
      </div>
      <p className="muted small">The date is used to turn “by Friday” into a real due date.</p>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <button type="submit" className="primary" disabled={busy}>
        {busy ? "Uploading…" : "Generate notes"}
      </button>
    </form>
  );
}
