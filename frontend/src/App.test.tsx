import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import App from "./App";
import { config, meeting, mockFetch } from "./test/fixtures";

describe("App", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  it("lists meetings and opens one", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/config": () => ({ body: config }),
      "GET /api/meetings": () => ({ body: { items: [meeting({ title: "Launch sync" })], total: 1 } }),
      "GET /api/meetings/m-1": () => ({ body: meeting() }),
    });
    render(<App />);
    expect(screen.getByRole("form", { name: "New meeting" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /Launch sync/ }));
    expect(window.location.hash).toBe("#/meetings/m-1");
    expect(await screen.findByText("The team moved the launch to the 10th.")).toBeInTheDocument();
  });

  it("opens the meeting from the URL hash", async () => {
    window.location.hash = "#/meetings/m-1";
    mockFetch({
      "GET /api/config": () => ({ body: config }),
      "GET /api/meetings": () => ({ body: { items: [], total: 0 } }),
      "GET /api/meetings/m-1": () => ({ body: meeting() }),
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Launch sync" })).toBeInTheDocument();
  });

  it("shows the empty state and demo banner", async () => {
    mockFetch({
      "GET /api/config": () => ({ body: { ...config, demo_mode: true } }),
      "GET /api/meetings": () => ({ body: { items: [], total: 0 } }),
    });
    render(<App />);
    expect(await screen.findByText(/No meetings yet/)).toBeInTheDocument();
    expect(await screen.findByRole("status")).toHaveTextContent("Demo mode");
  });

  it("navigates to a new meeting after upload", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/config": () => ({ body: config }),
      "GET /api/meetings": () => ({ body: { items: [], total: 0 } }),
      "POST /api/meetings/transcript": () => ({ status: 202, body: meeting({ id: "m-2", status: "queued" }) }),
      "GET /api/meetings/m-2": () => ({ body: meeting({ id: "m-2" }) }),
    });
    render(<App />);
    await user.click(screen.getByRole("tab", { name: "Paste transcript" }));
    await user.type(screen.getByLabelText("Transcript"), "Ana: hi");
    await user.click(screen.getByRole("button", { name: "Generate notes" }));
    expect(window.location.hash).toBe("#/meetings/m-2");
    expect(await screen.findByRole("heading", { name: "Launch sync" })).toBeInTheDocument();
  });

  it("shows a list error when the backend is down", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/reach the server/);
  });
});
