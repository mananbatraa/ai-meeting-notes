import { mockFetch } from "../test/fixtures";
import { api, ApiError } from "./api";

describe("api client", () => {
  it("uploads a file as multipart with date and trimmed title", async () => {
    const { calls } = mockFetch({ "POST /api/meetings": () => ({ status: 202, body: { id: "x" } }) });
    const file = new File(["audio"], "a.mp3");
    await api.uploadMeeting(file, { meetingDate: "2026-11-25", title: "  Sync " });
    const form = calls[0]!.init!.body as FormData;
    expect(form.get("file")).toBeInstanceOf(File);
    expect(form.get("meeting_date")).toBe("2026-11-25");
    expect(form.get("title")).toBe("Sync");
  });

  it("omits a blank title", async () => {
    const { calls } = mockFetch({ "POST /api/meetings": () => ({ status: 202, body: {} }) });
    await api.uploadMeeting(new File(["a"], "a.mp3"), { title: "  " });
    expect((calls[0]!.init!.body as FormData).has("title")).toBe(false);
  });

  it("posts pasted transcripts as JSON with nulls for empty fields", async () => {
    const { calls } = mockFetch({ "POST /api/meetings/transcript": () => ({ status: 202, body: {} }) });
    await api.submitTranscript("Ana: hi", {});
    expect(JSON.parse(calls[0]!.init!.body as string)).toEqual({ text: "Ana: hi", title: null, meeting_date: null });
  });

  it("passes pagination params", async () => {
    const { calls } = mockFetch({ "GET /api/meetings": () => ({ body: { items: [], total: 0 } }) });
    await api.listMeetings(5, 10);
    expect(calls[0]!.url).toBe("/api/meetings?limit=5&offset=10");
  });

  it("encodes ids in paths", async () => {
    const { calls } = mockFetch({});
    await expect(api.getMeeting("a/b")).rejects.toBeInstanceOf(ApiError);
    expect(calls[0]!.url).toBe("/api/meetings/a%2Fb");
  });

  it("surfaces FastAPI string details", async () => {
    mockFetch({ "POST /api/meetings": () => ({ status: 413, body: { detail: "file exceeds 1 MB" } }) });
    await expect(api.uploadMeeting(new File(["a"], "a.mp3"))).rejects.toMatchObject({
      status: 413,
      message: "file exceeds 1 MB",
    });
  });

  it("flattens validation errors", async () => {
    mockFetch({
      "POST /api/meetings/transcript": () => ({
        status: 422,
        body: { detail: [{ loc: ["body", "text"], msg: "String should have at least 1 character" }] },
      }),
    });
    await expect(api.submitTranscript("")).rejects.toThrow("text: String should have at least 1 character");
  });

  it("falls back to the HTTP status for non-JSON errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>", { status: 502 })));
    await expect(api.config()).rejects.toThrow("Request failed (HTTP 502)");
  });

  it("reports network failures clearly", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(api.config()).rejects.toMatchObject({ status: 0, message: expect.stringMatching(/reach the server/) });
  });

  it("returns undefined for 204 and text for markdown", async () => {
    mockFetch({
      "DELETE /api/meetings/m": () => ({ status: 204 }),
      "GET /api/meetings/m/markdown": () => ({ body: "# Notes" }),
    });
    await expect(api.deleteMeeting("m")).resolves.toBeUndefined();
    await expect(api.markdown("m")).resolves.toBe("# Notes");
  });
});
