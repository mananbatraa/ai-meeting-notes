import { expect, test, type Page } from "@playwright/test";

// A WAV header is enough: in demo mode the transcriber returns the built-in demo
// transcript without decoding audio, and the extractor returns the demo notes.
function silentWav(): Buffer {
  const dataLen = 1600;
  const buf = Buffer.alloc(44 + dataLen);
  buf.write("RIFF", 0);
  buf.writeUInt32LE(36 + dataLen, 4);
  buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20); // PCM
  buf.writeUInt16LE(1, 22); // mono
  buf.writeUInt32LE(16000, 24);
  buf.writeUInt32LE(32000, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write("data", 36);
  buf.writeUInt32LE(dataLen, 40);
  return buf;
}

async function uploadDemoRecording(page: Page, name: string): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("Demo mode");
  await page.getByLabel("Meeting file").setInputFiles({ name, mimeType: "audio/wav", buffer: silentWav() });
  await page.getByRole("button", { name: "Generate notes" }).click();
  await expect(page).toHaveURL(/#\/meetings\/[\w-]+$/);
  await expect(page.getByRole("heading", { name: "Summary" })).toBeVisible({ timeout: 20_000 });
}

test("upload a recording, get notes, check off and edit action items", async ({ page }) => {
  await uploadDemoRecording(page, "weekly-sync.wav");

  await expect(page.getByRole("heading", { level: 2 })).toHaveText("Mobile launch weekly sync");
  await expect(page.getByRole("heading", { name: "Action items" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Decisions" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Transcript" })).toBeVisible();

  const sdkTask = "Finish the payments SDK upgrade for Android";
  const done = page.getByRole("checkbox", { name: `Done: ${sdkTask}` });
  await expect(done).not.toBeChecked();
  await done.check();
  await expect(done).toBeChecked();

  // Correct an owner the model got wrong.
  const alertsTask = "Set up crash reporting alerts";
  await page.getByRole("button", { name: `Edit: ${alertsTask}` }).click();
  await page.getByLabel("Edit owner").fill("Priya");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("row", { name: new RegExp(alertsTask) })).toContainText("Priya");

  // Add an item the model missed, then remove another one.
  await page.getByLabel("New item task").fill("Book the launch retro");
  await page.getByLabel("New item owner").fill("Lee");
  await page.getByRole("button", { name: "Add item" }).click();
  await expect(page.getByRole("row", { name: /Book the launch retro/ })).toContainText("Lee");

  const marketingTask = "Tell marketing about the new launch date and update the launch brief";
  await page.getByRole("button", { name: `Remove: ${marketingTask}` }).click();
  await expect(page.getByRole("checkbox", { name: `Done: ${marketingTask}` })).toHaveCount(0);

  // Everything above was persisted by the API, not just held in React state.
  await page.reload();
  await expect(page.getByRole("checkbox", { name: `Done: ${sdkTask}` })).toBeChecked();
  await expect(page.getByRole("row", { name: new RegExp(alertsTask) })).toContainText("Priya");
  await expect(page.getByRole("row", { name: /Book the launch retro/ })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: `Done: ${marketingTask}` })).toHaveCount(0);

  // The Markdown export reflects the edits.
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download .md" }).click();
  const file = await (await download).createReadStream();
  let markdown = "";
  for await (const chunk of file) markdown += chunk.toString();
  expect(markdown).toContain("# Mobile launch weekly sync");
  expect(markdown).toContain("Book the launch retro");
  expect(markdown).not.toContain(marketingTask);
});

test("paste a transcript, see it in the sidebar, then delete it", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Paste transcript" }).click();
  await page.getByLabel("Transcript").fill("Ana: Kickoff for the billing revamp.\nBo: I'll draft the schema.");
  await page.getByLabel("Title (optional)").fill("Billing revamp kickoff");
  await page.getByRole("button", { name: "Generate notes" }).click();

  await expect(page.getByRole("heading", { name: "Summary" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { level: 2 })).toHaveText("Billing revamp kickoff");
  const sidebar = page.locator("aside");
  await expect(sidebar.getByText("Billing revamp kickoff")).toBeVisible();

  await page.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("form", { name: "New meeting" })).toBeVisible();
  await expect(sidebar.getByText("Billing revamp kickoff")).toHaveCount(0);
});

test("a meeting link survives a reload and the back button", async ({ page }) => {
  await uploadDemoRecording(page, "deep-link.wav");
  const url = page.url();

  await page.getByRole("button", { name: "+ New meeting" }).click();
  await expect(page.getByRole("form", { name: "New meeting" })).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(url);
  await expect(page.getByRole("heading", { name: "Summary" })).toBeVisible();

  await page.goto(url);
  await expect(page.getByRole("heading", { level: 2 })).toHaveText("Mobile launch weekly sync");
});
