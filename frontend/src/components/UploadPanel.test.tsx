import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { config, mockFetch } from "../test/fixtures";
import { UploadPanel } from "./UploadPanel";

const created = {
  id: "new-1",
  filename: "sync.mp3",
  status: "queued",
  title: null,
  meeting_date: "2026-11-25",
  created_at: "",
  updated_at: "",
  error: null,
};

describe("UploadPanel", () => {
  it("uploads a chosen file with the meeting date and title", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch({ "POST /api/meetings": () => ({ status: 202, body: created }) });
    const onCreated = vi.fn();
    render(<UploadPanel config={config} onCreated={onCreated} />);

    await user.upload(screen.getByLabelText("Meeting file"), new File(["audio"], "sync.mp3"));
    expect(screen.getByText("sync.mp3")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Title (optional)"), "Launch sync");
    const date = screen.getByLabelText("Meeting date");
    await user.clear(date);
    await user.type(date, "2026-11-20");
    await user.click(screen.getByRole("button", { name: "Generate notes" }));

    expect(onCreated).toHaveBeenCalledWith(created);
    const form = calls[0]!.init!.body as FormData;
    expect((form.get("file") as File).name).toBe("sync.mp3");
    expect(form.get("title")).toBe("Launch sync");
    expect(form.get("meeting_date")).toBe("2026-11-20");
  });

  it("rejects unsupported files before uploading", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const { fn } = mockFetch({});
    render(<UploadPanel config={config} onCreated={vi.fn()} />);
    await user.upload(screen.getByLabelText("Meeting file"), new File(["x"], "notes.pdf"));
    expect(screen.getByRole("alert")).toHaveTextContent(".pdf is not supported");
    await user.click(screen.getByRole("button", { name: "Generate notes" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a recording");
    expect(fn).not.toHaveBeenCalled();
  });

  it("accepts dropped files", async () => {
    mockFetch({});
    render(<UploadPanel config={config} onCreated={vi.fn()} />);
    const zone = screen.getByText(/Drop a recording here/).closest("label")!;
    const file = new File(["WEBVTT"], "call.vtt");
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
    expect(screen.getByText("call.vtt")).toBeInTheDocument();
  });

  it("submits a pasted transcript", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch({ "POST /api/meetings/transcript": () => ({ status: 202, body: created }) });
    const onCreated = vi.fn();
    render(<UploadPanel config={config} onCreated={onCreated} />);
    await user.click(screen.getByRole("tab", { name: "Paste transcript" }));
    await user.click(screen.getByRole("button", { name: "Generate notes" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Paste the transcript text.");

    await user.type(screen.getByLabelText("Transcript"), "Ana: Ben, send the report.");
    await user.click(screen.getByRole("button", { name: "Generate notes" }));
    expect(onCreated).toHaveBeenCalled();
    expect(JSON.parse(calls[0]!.init!.body as string).text).toBe("Ana: Ben, send the report.");
  });

  it("shows server errors and stays on the form", async () => {
    const user = userEvent.setup();
    mockFetch({ "POST /api/meetings": () => ({ status: 413, body: { detail: "file exceeds 1 MB" } }) });
    const onCreated = vi.fn();
    render(<UploadPanel config={config} onCreated={onCreated} />);
    await user.upload(screen.getByLabelText("Meeting file"), new File(["a"], "a.wav"));
    await user.click(screen.getByRole("button", { name: "Generate notes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("file exceeds 1 MB");
    expect(onCreated).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Generate notes" })).toBeEnabled();
  });
});
