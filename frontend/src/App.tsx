import { useCallback, useEffect, useState } from "react";

import { MeetingList } from "./components/MeetingList";
import { MeetingView } from "./components/MeetingView";
import { UploadPanel } from "./components/UploadPanel";
import { useMeetings } from "./hooks/useMeetings";
import { api } from "./lib/api";
import type { PublicConfig } from "./lib/types";

function idFromHash(hash: string): string | null {
  const m = /^#\/meetings\/([\w-]+)$/.exec(hash);
  return m?.[1] ?? null;
}

export default function App() {
  const [selected, setSelected] = useState<string | null>(() => idFromHash(window.location.hash));
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const meetings = useMeetings();

  useEffect(() => {
    api.config().then(setConfig, () => setConfig(null));
    const onHash = () => setSelected(idFromHash(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const select = useCallback((id: string | null) => {
    window.location.hash = id ? `/meetings/${id}` : "";
    setSelected(id);
  }, []);

  const { reload } = meetings;
  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>
          <button type="button" className="home" onClick={() => select(null)}>
            Meeting Notes
          </button>
        </h1>
        <button type="button" className="primary wide" onClick={() => select(null)}>
          + New meeting
        </button>
        <MeetingList
          items={meetings.items}
          selectedId={selected}
          loading={meetings.loading}
          error={meetings.error}
          onSelect={select}
        />
      </aside>
      <main className="content">
        {config?.demo_mode && (
          <p className="banner" role="status">
            Demo mode: transcription and/or notes are generated offline, not by Whisper and Claude.
          </p>
        )}
        {selected ? (
          <MeetingView
            key={selected}
            id={selected}
            onChanged={reload}
            onDeleted={() => {
              select(null);
              reload();
            }}
          />
        ) : (
          <UploadPanel
            config={config}
            onCreated={(m) => {
              reload();
              select(m.id);
            }}
          />
        )}
      </main>
    </div>
  );
}
