import { formatTimestamp } from "../lib/format";
import type { Transcript } from "../lib/types";

interface Props {
  transcript: Transcript;
  highlight: number | null;
}

/** Index of the segment that contains `seconds` (or the last one starting before it). */
export function segmentAt(transcript: Transcript, seconds: number): number {
  let found = -1;
  transcript.segments.forEach((s, i) => {
    if (s.start <= seconds + 0.01) found = i;
  });
  return found;
}

export function TranscriptView({ transcript, highlight }: Props) {
  const active = highlight === null ? -1 : segmentAt(transcript, highlight);
  return (
    <ol className="transcript">
      {transcript.segments.map((seg, i) => (
        <li
          key={i}
          id={`seg-${i}`}
          className={i === active ? "segment active" : "segment"}
          aria-current={i === active ? "true" : undefined}
        >
          <span className="ts-label">{formatTimestamp(seg.start)}</span>
          {seg.speaker && <strong className="speaker">{seg.speaker}</strong>}
          <span>{seg.text}</span>
        </li>
      ))}
    </ol>
  );
}
