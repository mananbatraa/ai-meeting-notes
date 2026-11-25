import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { notes } from "../test/fixtures";
import { ActionItemsTable } from "./ActionItemsTable";

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
