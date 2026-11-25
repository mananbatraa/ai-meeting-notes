import { notes } from "../test/fixtures";
import { checkFile, fileExtension, formatDate, formatTimestamp, owners, sortActionItems, todayIso } from "./format";

describe("formatTimestamp", () => {
  it.each([
    [0, "0:00"],
    [65.9, "1:05"],
    [3723, "1:02:03"],
    [-5, "0:00"],
  ])("%s -> %s", (secs, out) => {
    expect(formatTimestamp(secs)).toBe(out);
  });
});

describe("dates", () => {
  it("formats ISO dates as local calendar dates", () => {
    expect(formatDate("2026-11-27")).toBe("Fri, Nov 27");
  });
  it("returns unparseable input unchanged", () => {
    expect(formatDate("soon")).toBe("soon");
  });
  it("builds today's ISO date from local time", () => {
    expect(todayIso(new Date(2026, 0, 5, 23, 30))).toBe("2026-01-05");
  });
});

describe("action items", () => {
  it("sorts dated items first, soonest first", () => {
    expect(sortActionItems(notes.action_items).map((i) => i.task)).toEqual([
      "Finish SDK upgrade",
      "Set up crash alerts",
      "Write launch brief",
    ]);
  });
  it("breaks ties by priority", () => {
    const items = [
      { ...notes.action_items[0]!, task: "low", priority: "low" as const },
      { ...notes.action_items[0]!, task: "high", priority: "high" as const },
    ];
    expect(sortActionItems(items).map((i) => i.task)).toEqual(["high", "low"]);
  });
  it("does not mutate the input", () => {
    const copy = [...notes.action_items];
    sortActionItems(notes.action_items);
    expect(notes.action_items).toEqual(copy);
  });
  it("lists distinct owners alphabetically", () => {
    expect(owners(notes.action_items)).toEqual(["Lee", "Sam"]);
  });
});

describe("file checks", () => {
  const allowed = [".mp3", ".vtt"];
  it("reads lowercased extensions", () => {
    expect(fileExtension("Call.MP3")).toBe(".mp3");
    expect(fileExtension(".hidden")).toBe("");
    expect(fileExtension("noext")).toBe("");
  });
  it("accepts allowed files within the limit", () => {
    expect(checkFile(new File(["x"], "a.mp3"), allowed, 1)).toEqual({ ok: true });
  });
  it("rejects other types", () => {
    expect(checkFile(new File(["x"], "a.exe"), allowed, 1).error).toMatch(/\.exe is not supported/);
  });
  it("rejects empty and oversized files", () => {
    expect(checkFile(new File([], "a.mp3"), allowed, 1).error).toMatch(/empty/);
    const big = new File([new Uint8Array(1024 * 1024 + 1)], "a.mp3");
    expect(checkFile(big, allowed, 1).error).toMatch(/larger than 1 MB/);
  });
});
