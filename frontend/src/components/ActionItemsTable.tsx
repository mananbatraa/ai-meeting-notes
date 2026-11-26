import { useId, useMemo, useState, type FormEvent } from "react";

import { formatDate, formatTimestamp, owners, sortActionItems } from "../lib/format";
import type { ActionItem, ActionItemCreate, ActionItemPatch, Priority } from "../lib/types";

export interface ActionItemHandlers {
  onUpdate: (id: string, patch: ActionItemPatch) => Promise<void>;
  onAdd: (item: ActionItemCreate) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

interface Props {
  items: ActionItem[];
  meetingDate: string;
  onSeek?: (seconds: number) => void;
  /** When given, items can be checked off, edited, added and removed. */
  editing?: ActionItemHandlers;
}

const ALL = "__all__";
const UNASSIGNED = "__none__";
const PRIORITIES: Priority[] = ["high", "medium", "low"];

interface Draft {
  task: string;
  owner: string;
  due_date: string;
  priority: Priority;
}

const emptyDraft: Draft = { task: "", owner: "", due_date: "", priority: "medium" };

function toDraft(item: ActionItem): Draft {
  return { task: item.task, owner: item.owner ?? "", due_date: item.due_date ?? "", priority: item.priority };
}

function fromDraft(d: Draft): ActionItemCreate {
  return { task: d.task.trim(), owner: d.owner.trim() || null, due_date: d.due_date || null, priority: d.priority };
}

/** Only the fields that changed, so an unchanged save is not recorded as an edit. */
function diff(item: ActionItem, d: Draft): ActionItemPatch {
  const next = fromDraft(d);
  const patch: ActionItemPatch = {};
  if (next.task !== item.task) patch.task = next.task;
  if (next.owner !== item.owner) patch.owner = next.owner;
  if (next.due_date !== item.due_date) patch.due_date = next.due_date;
  if (next.priority !== item.priority) patch.priority = next.priority;
  return patch;
}

function DraftFields({ draft, onChange, label }: { draft: Draft; onChange: (d: Draft) => void; label: string }) {
  return (
    <>
      <input
        aria-label={`${label} task`}
        placeholder="Task"
        value={draft.task}
        required
        maxLength={500}
        onChange={(e) => onChange({ ...draft, task: e.target.value })}
      />
      <input
        aria-label={`${label} owner`}
        placeholder="Owner"
        value={draft.owner}
        maxLength={100}
        onChange={(e) => onChange({ ...draft, owner: e.target.value })}
      />
      <input
        aria-label={`${label} due date`}
        type="date"
        value={draft.due_date}
        onChange={(e) => onChange({ ...draft, due_date: e.target.value })}
      />
      <select
        aria-label={`${label} priority`}
        value={draft.priority}
        onChange={(e) => onChange({ ...draft, priority: e.target.value as Priority })}
      >
        {PRIORITIES.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>
    </>
  );
}

export function ActionItemsTable({ items, meetingDate, onSeek, editing }: Props) {
  const [owner, setOwner] = useState(ALL);
  const [hideDone, setHideDone] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [newItem, setNewItem] = useState<Draft>(emptyDraft);
  const [busy, setBusy] = useState(false);
  const filterId = useId();
  const people = useMemo(() => owners(items), [items]);
  const doneCount = items.filter((i) => i.done).length;
  const rows = useMemo(() => {
    let sorted = sortActionItems(items);
    if (hideDone) sorted = sorted.filter((i) => !i.done);
    if (owner === ALL) return sorted;
    if (owner === UNASSIGNED) return sorted.filter((i) => !i.owner);
    return sorted.filter((i) => i.owner === owner);
  }, [items, owner, hideDone]);
  const columns = editing ? 6 : 4;

  const guard = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
      return true;
    } catch {
      return false; // the parent shows the error
    } finally {
      setBusy(false);
    }
  };

  const save = async (e: FormEvent, item: ActionItem) => {
    e.preventDefault();
    if (!editing) return;
    const patch = diff(item, draft);
    if (Object.keys(patch).length === 0 || (await guard(() => editing.onUpdate(item.id, patch)))) {
      setEditingId(null);
    }
  };

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing || !newItem.task.trim()) return;
    if (await guard(() => editing.onAdd(fromDraft(newItem)))) setNewItem(emptyDraft);
  };

  return (
    <>
      {items.length === 0 ? (
        <p className="muted">No action items were assigned.</p>
      ) : (
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
            {editing && (
              <>
                <label className="inline">
                  <input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)} />
                  Hide done
                </label>
                <span className="muted small" aria-live="polite">
                  {doneCount} of {items.length} done
                </span>
              </>
            )}
          </div>
          <table className="actions">
            <thead>
              <tr>
                {editing && (
                  <th scope="col">
                    <span className="sr-only">Done</span>
                  </th>
                )}
                <th scope="col">Task</th>
                <th scope="col">Owner</th>
                <th scope="col">Due</th>
                <th scope="col">Priority</th>
                {editing && (
                  <th scope="col">
                    <span className="sr-only">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((item) =>
                editing && editingId === item.id ? (
                  <tr key={item.id} className="editing">
                    <td colSpan={columns}>
                      <form className="item-form" onSubmit={(e) => void save(e, item)}>
                        <DraftFields draft={draft} onChange={setDraft} label="Edit" />
                        <button type="submit" className="primary" disabled={busy || !draft.task.trim()}>
                          Save
                        </button>
                        <button type="button" onClick={() => setEditingId(null)}>
                          Cancel
                        </button>
                      </form>
                    </td>
                  </tr>
                ) : (
                  <tr key={item.id} className={item.done ? "done" : undefined}>
                    {editing && (
                      <td>
                        <input
                          type="checkbox"
                          checked={item.done}
                          disabled={busy}
                          aria-label={`Done: ${item.task}`}
                          onChange={(e) => void guard(() => editing.onUpdate(item.id, { done: e.target.checked }))}
                        />
                      </td>
                    )}
                    <td>
                      <span className="task">{item.task}</span>
                      {item.edited && <span className="tag">edited</span>}
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
                        <span className={item.due_date === meetingDate ? "date due-today" : "date"}>
                          {formatDate(item.due_date)}
                        </span>
                      ) : (
                        <span className="muted">-</span>
                      )}
                    </td>
                    <td>
                      <span className={`priority priority-${item.priority}`}>{item.priority}</span>
                    </td>
                    {editing && (
                      <td className="row-actions">
                        <button
                          type="button"
                          className="link"
                          aria-label={`Edit: ${item.task}`}
                          onClick={() => {
                            setDraft(toDraft(item));
                            setEditingId(item.id);
                          }}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="link danger"
                          disabled={busy}
                          aria-label={`Remove: ${item.task}`}
                          onClick={() => void guard(() => editing.onDelete(item.id))}
                        >
                          Remove
                        </button>
                      </td>
                    )}
                  </tr>
                ),
              )}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={columns} className="muted">
                    {hideDone && owner === ALL ? "Everything is done." : "Nothing for this owner."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}
      {editing && (
        <form className="item-form add-item" onSubmit={(e) => void add(e)}>
          <DraftFields draft={newItem} onChange={setNewItem} label="New item" />
          <button type="submit" disabled={busy || !newItem.task.trim()}>
            Add item
          </button>
        </form>
      )}
    </>
  );
}
