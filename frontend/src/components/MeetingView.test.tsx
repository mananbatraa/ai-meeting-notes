import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { POLL_INTERVAL_MS } from "../hooks/useMeeting";
import { meeting, mockFetch } from "../test/fixtures";
import type { MeetingDetail } from "../lib/types";
import { MeetingView } from "./MeetingView";

function sequence(...states: MeetingDetail[]) {
  let i = 0;
  return () => ({ body: states[Math.min(i++, states.length - 1)] });
}

describe("MeetingView", () => {
  it("polls until the meeting completes, then shows notes", async () => {
    vi.useFakeTimers();
    try {
      const { calls } = mockFetch({
        "GET /api/meetings/m-1": sequence(
          meeting({ status: "queued", notes: null, transcript: null }),
          meeting({ status: "extracting", notes: null }),
          meeting(),
        ),
      });
      const onChanged = vi.fn();
      render(<MeetingView id="m-1" onChanged={onChanged} onDeleted={vi.fn()} />);

      await act(async () => {});
      expect(screen.getByRole("list", { name: "Processing progress" })).toBeInTheDocument();
      expect(screen.getByText("Queued", { selector: "li" })).toHaveAttribute("aria-current", "step");

      await act(async () => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
      expect(screen.getByText("Writing notes", { selector: "li" })).toHaveAttribute("aria-current", "step");

      await act(async () => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS));
      expect(screen.getByText("The team moved the launch to the 10th.")).toBeInTheDocument();
      expect(screen.queryByRole("list", { name: "Processing progress" })).not.toBeInTheDocument();

      await act(async () => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5));
      expect(calls).toHaveLength(3); // stops polling once completed
      expect(onChanged).toHaveBeenCalledTimes(3); // once per status change
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders decisions, open questions and the transcript", async () => {
    mockFetch({ "GET /api/meetings/m-1": () => ({ body: meeting() }) });
    render(<MeetingView id="m-1" onChanged={vi.fn()} onDeleted={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "Launch sync" })).toBeInTheDocument();
    expect(screen.getByText("Launch on the 10th")).toBeInTheDocument();
    expect(screen.getByText("Need beta feedback")).toBeInTheDocument();
    expect(screen.getByText("Do we need the press kit?")).toBeInTheDocument();
    expect(screen.getByText("With Priya, Sam, Lee")).toBeInTheDocument();
    expect(screen.getByText("I'll finish the SDK upgrade by Friday.")).toBeInTheDocument();
  });

  it("highlights the transcript line for a clicked timestamp", async () => {
    const user = userEvent.setup();
    mockFetch({ "GET /api/meetings/m-1": () => ({ body: meeting() }) });
    render(<MeetingView id="m-1" onChanged={vi.fn()} onDeleted={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Jump to 0:15 in transcript" }));
    const line = screen.getByText("I'll finish the SDK upgrade by Friday.").closest("li")!;
    expect(line).toHaveClass("active");
    expect(line).toHaveAttribute("aria-current", "true");
  });

  it("shows the error for a failed meeting and retries it", async () => {
    const user = userEvent.setup();
    let status: "failed" | "completed" = "failed";
    const { calls } = mockFetch({
      "GET /api/meetings/m-1": () => ({
        body:
          status === "failed"
            ? meeting({ status: "failed", notes: null, error: "Claude API rate limit reached" })
            : meeting(),
      }),
      "POST /api/meetings/m-1/retry": () => {
        status = "completed";
        return { status: 202, body: meeting({ status: "queued", notes: null }) };
      },
    });
    const onChanged = vi.fn();
    render(<MeetingView id="m-1" onChanged={onChanged} onDeleted={vi.fn()} />);
    expect(await screen.findByText("Claude API rate limit reached")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("The team moved the launch to the 10th.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(true);
    expect(onChanged).toHaveBeenCalled();
  });

  it("deletes a finished meeting", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch({
      "GET /api/meetings/m-1": () => ({ body: meeting() }),
      "DELETE /api/meetings/m-1": () => ({ status: 204 }),
    });
    const onDeleted = vi.fn();
    render(<MeetingView id="m-1" onChanged={vi.fn()} onDeleted={onDeleted} />);
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    expect(onDeleted).toHaveBeenCalled();
    expect(calls.at(-1)!.method).toBe("DELETE");
  });

  it("does not offer delete while processing", async () => {
    mockFetch({ "GET /api/meetings/m-1": () => ({ body: meeting({ status: "transcribing", notes: null }) }) });
    render(<MeetingView id="m-1" onChanged={vi.fn()} onDeleted={vi.fn()} />);
    await screen.findByRole("list", { name: "Processing progress" });
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("copies Markdown to the clipboard", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/meetings/m-1": () => ({ body: meeting() }),
      "GET /api/meetings/m-1/markdown": () => ({ body: "# Launch sync" }),
    });
    render(<MeetingView id="m-1" onChanged={vi.fn()} onDeleted={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "Copy Markdown" }));
    expect(await navigator.clipboard.readText()).toBe("# Launch sync");
    expect(screen.getByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("says when the meeting does not exist", async () => {
    mockFetch({});
    render(<MeetingView id="gone" onChanged={vi.fn()} onDeleted={vi.fn()} />);
    expect(await screen.findByText("This meeting no longer exists.")).toBeInTheDocument();
  });

  it("keeps polling through transient network errors", async () => {
    vi.useFakeTimers();
    try {
      let n = 0;
      vi.stubGlobal(
        "fetch",
        vi.fn(async () => {
          n += 1;
          if (n === 1) throw new TypeError("Failed to fetch");
          return new Response(JSON.stringify(meeting()), { headers: { "content-type": "application/json" } });
        }),
      );
      render(<MeetingView id="m-1" onChanged={vi.fn()} onDeleted={vi.fn()} />);
      await act(async () => {});
      expect(screen.getByRole("alert")).toHaveTextContent(/reach the server/);
      await act(async () => vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2));
      expect(screen.getByText("The team moved the launch to the 10th.")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
