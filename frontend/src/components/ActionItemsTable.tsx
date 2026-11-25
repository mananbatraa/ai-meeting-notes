import { useId, useMemo, useState } from "react";

import { formatDate, formatTimestamp, owners, sortActionItems } from "../lib/format";
import type { ActionItem } from "../lib/types";

interface Props {
  items: ActionItem[];
  meetingDate: string;
  onSeek?: (seconds: number) => void;
}

const ALL = "__all__";
const UNASSIGNED = "__none__";

export function ActionItemsTable({ items, meetingDate, onSeek }: Props) {
  const [owner, setOwner] = useState(ALL);
  const filterId = useId();
  const people = useMemo(() => owners(items), [items]);
  const rows = useMemo(() => {
    const sorted = sortActionItems(items);
    if (owner === ALL) return sorted;
    if (owner === UNASSIGNED) return sorted.filter((i) => !i.owner);
    return sorted.filter((i) => i.owner === owner);
  }, [items, owner]);

  if (items.length === 0) return <p className="muted">No action items were assigned.</p>;

  return (
    <>
      <div className="table-tools">
        <label htmlFor={filterId}>Owner</label>
        <select id={filterId} value={owner} onChange={(e) => setOwner(e.target.value)}>
          <option value={ALL}>Everyone ({items.length})</option>
          {people.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
          <option value={UNASSIGNED}>Unassigned</option>
        </select>
      </div>
      <table className="actions">
        <thead>
          <tr>
            <th scope="col">Task</th>
            <th scope="col">Owner</th>
            <th scope="col">Due</th>
            <th scope="col">Priority</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((item, i) => (
            <tr key={`${item.task}-${i}`}>
              <td>
                {item.task}
                {item.timestamp_s !== null && onSeek && (
                  <button
                    type="button"
                    className="ts"
                    onClick={() => onSeek(item.timestamp_s as number)}
                    aria-label={`Jump to ${formatTimestamp(item.timestamp_s)} in transcript`}
                  >
                    {formatTimestamp(item.timestamp_s)}
                  </button>
                )}
              </td>
              <td>{item.owner ?? <span className="muted">Unassigned</span>}</td>
              <td>
                {item.due_date ? (
                  <span className={item.due_date === meetingDate ? "due-today" : undefined}>
                    {formatDate(item.due_date)}
                  </span>
                ) : (
                  <span className="muted">-</span>
                )}
              </td>
              <td>
                <span className={`priority priority-${item.priority}`}>{item.priority}</span>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={4} className="muted">
                Nothing for this owner.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </>
  );
}
