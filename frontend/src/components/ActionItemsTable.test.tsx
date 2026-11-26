import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { item, notes } from "../test/fixtures";
import { ActionItemsTable, type ActionItemHandlers } from "./ActionItemsTable";

const taskCells = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("cell")[0]!.textContent);

describe("ActionItemsTable", () => {
  it("shows items sorted by due date with owners and priorities", () => {
    render(<ActionItemsTable items={notes.action_items} meetingDate="2026-11-25" />);
    expect(taskCells()).toEqual(["Finish SDK upgrade", "Set up crash alerts", "Write launch brief"]);
    const first = screen.getAllByRole("row")[1]!;
    expect(within(first).getByText("Sam")).toBeInTheDocument();
    expect(within(first).getByText("Fri, Nov 27")).toBeInTheDocument();
    expect(within(first).getByText("high")).toHaveClass("priority-high");
    expect(screen.getByText("Unassigned", { selector: "td span" })).toBeInTheDocument();
  });

  it("filters by owner and unassigned", async () => {
    const user = userEvent.setup();
    render(<ActionItemsTable items={notes.action_items} meetingDate="2026-11-25" />);
    const select = screen.getByLabelText("Owner");
    await user.selectOptions(select, "Lee");
    expect(taskCells()).toEqual(["Write launch brief"]);
    await user.selectOptions(select, "Unassigned");
    expect(taskCells()).toEqual(["Set up crash alerts"]);
    await user.selectOptions(select, "Everyone (3)");
    expect(taskCells()).toHaveLength(3);
  });

  it("jumps to the transcript from a timestamp", async () => {
    const onSeek = vi.fn();
    render(<ActionItemsTable items={notes.action_items} meetingDate="2026-11-25" onSeek={onSeek} />);
    await userEvent.click(screen.getByRole("button", { name: "Jump to 0:15 in transcript" }));
    expect(onSeek).toHaveBeenCalledWith(15);
    // items without a timestamp get no button
    expect(screen.getAllByRole("button", { name: /Jump to/ })).toHaveLength(2);
  });

  it("hides timestamp buttons without a transcript", () => {
    render(<ActionItemsTable items={notes.action_items} meetingDate="2026-11-25" />);
    expect(screen.queryByRole("button", { name: /Jump to/ })).not.toBeInTheDocument();
  });

  it("renders an empty state", () => {
    render(<ActionItemsTable items={[]} meetingDate="2026-11-25" />);
    expect(screen.getByText("No action items were assigned.")).toBeInTheDocument();
  });
});

function handlers(overrides: Partial<ActionItemHandlers> = {}): ActionItemHandlers {
  return {
    onUpdate: vi.fn(async () => {}),
    onAdd: vi.fn(async () => {}),
    onDelete: vi.fn(async () => {}),
    ...overrides,
  };
}

/** Task text of each body row when the table is editable (column 0 is the checkbox). */
const editableTasks = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.querySelector(".task")?.textContent ?? null);

describe("ActionItemsTable editing", () => {
  it("is read-only without handlers", () => {
    render(<ActionItemsTable items={notes.action_items} meetingDate="2026-11-25" />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Edit/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add item" })).not.toBeInTheDocument();
  });

  it("checks an item off and shows progress", async () => {
    const h = handlers();
    const items = [notes.action_items[0]!, { ...notes.action_items[1]!, done: true }];
    render(<ActionItemsTable items={items} meetingDate="2026-11-25" editing={h} />);
    expect(screen.getByText("1 of 2 done")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Done: Finish SDK upgrade" })).toBeChecked();
    expect(screen.getByText("Finish SDK upgrade").closest("tr")).toHaveClass("done");

    await userEvent.click(screen.getByRole("checkbox", { name: "Done: Write launch brief" }));
    expect(h.onUpdate).toHaveBeenCalledWith("a1", { done: true });
  });

  it("hides done items", async () => {
    const items = [item({ id: "x", task: "Open one" }), item({ id: "y", task: "Closed one", done: true })];
    render(<ActionItemsTable items={items} meetingDate="2026-11-25" editing={handlers()} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Hide done" }));
    expect(editableTasks()).toEqual(["Open one"]);
  });

  it("says everything is done when all items are hidden", async () => {
    const items = [item({ id: "y", task: "Closed one", done: true })];
    render(<ActionItemsTable items={items} meetingDate="2026-11-25" editing={handlers()} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Hide done" }));
    expect(screen.getByText("Everything is done.")).toBeInTheDocument();
  });

  it("edits only the fields that changed", async () => {
    const user = userEvent.setup();
    const h = handlers();
    render(<ActionItemsTable items={notes.action_items} meetingDate="2026-11-25" editing={h} />);
    await user.click(screen.getByRole("button", { name: "Edit: Set up crash alerts" }));
    expect(screen.getByLabelText("Edit task")).toHaveValue("Set up crash alerts");
    await user.type(screen.getByLabelText("Edit owner"), "  Sam ");
    await user.selectOptions(screen.getByLabelText("Edit priority"), "high");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(h.onUpdate).toHaveBeenCalledWith("a3", { owner: "Sam", priority: "high" });
    expect(screen.queryByLabelText("Edit task")).not.toBeInTheDocument();
  });

  it("clears a due date by sending null", async () => {
    const user = userEvent.setup();
    const h = handlers();
    render(<ActionItemsTable items={notes.action_items} meetingDate="2026-11-25" editing={h} />);
    await user.click(screen.getByRole("button", { name: "Edit: Finish SDK upgrade" }));
    await user.clear(screen.getByLabelText("Edit due date"));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(h.onUpdate).toHaveBeenCalledWith("a2", { due_date: null });
  });

  it("saving without changes makes no request; cancel discards", async () => {
    const user = userEvent.setup();
    const h = handlers();
    render(<ActionItemsTable items={notes.action_items} meetingDate="2026-11-25" editing={h} />);
    await user.click(screen.getByRole("button", { name: "Edit: Write launch brief" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(h.onUpdate).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Edit: Write launch brief" }));
    await user.clear(screen.getByLabelText("Edit task"));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("Write launch brief")).toBeInTheDocument();
  });

  it("keeps the form open when saving fails", async () => {
    const user = userEvent.setup();
    const h = handlers({ onUpdate: vi.fn(async () => Promise.reject(new Error("nope"))) });
    render(<ActionItemsTable items={notes.action_items} meetingDate="2026-11-25" editing={h} />);
    await user.click(screen.getByRole("button", { name: "Edit: Write launch brief" }));
    await user.type(screen.getByLabelText("Edit task"), "!");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByLabelText("Edit task")).toHaveValue("Write launch brief!");
  });

  it("adds an item and resets the form", async () => {
    const user = userEvent.setup();
    const h = handlers();
    render(<ActionItemsTable items={[]} meetingDate="2026-11-25" editing={h} />);
    expect(screen.getByText("No action items were assigned.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add item" })).toBeDisabled();
    await user.type(screen.getByLabelText("New item task"), " Book the retro ");
    await user.type(screen.getByLabelText("New item due date"), "2026-12-02");
    await user.click(screen.getByRole("button", { name: "Add item" }));
    expect(h.onAdd).toHaveBeenCalledWith({
      task: "Book the retro",
      owner: null,
      due_date: "2026-12-02",
      priority: "medium",
    });
    expect(screen.getByLabelText("New item task")).toHaveValue("");
  });

  it("removes an item and marks edited ones", async () => {
    const h = handlers();
    const items = [item({ id: "z", task: "Fixed by hand", edited: true })];
    render(<ActionItemsTable items={items} meetingDate="2026-11-25" editing={h} />);
    expect(screen.getByText("edited")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove: Fixed by hand" }));
    expect(h.onDelete).toHaveBeenCalledWith("z");
  });
});
