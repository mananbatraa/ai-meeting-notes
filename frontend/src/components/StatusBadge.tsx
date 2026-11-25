import { STATUS_LABEL } from "../lib/format";
import type { JobStatus } from "../lib/types";

export function StatusBadge({ status }: { status: JobStatus }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABEL[status]}</span>;
}

const STEPS: JobStatus[] = ["queued", "transcribing", "extracting", "completed"];

/** Pipeline progress: queued -> transcribing -> writing notes -> done. */
export function ProgressSteps({ status }: { status: JobStatus }) {
  const current = STEPS.indexOf(status);
  return (
    <ol className="steps" aria-label="Processing progress">
      {STEPS.map((step, i) => {
        const state = i < current ? "done" : i === current ? "active" : "todo";
        return (
          <li key={step} className={`step step-${state}`} aria-current={state === "active" ? "step" : undefined}>
            {STATUS_LABEL[step]}
          </li>
        );
      })}
    </ol>
  );
}
