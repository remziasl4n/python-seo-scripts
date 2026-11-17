import { expect, test } from "@playwright/test";

// Sites, run history and setup. Test sites are named e2e-<time> and always cleaned up.

test.afterEach(async ({ request }) => {
  const { sites } = await (await request.get("/api/sites")).json();
  for (const site of sites as { name: string }[]) {
    if (site.name.startsWith("e2e-")) await request.delete(`/api/sites/${site.name}`);
  }
});

test("create, edit and delete a site", async ({ page }) => {
  const name = `e2e-${Date.now()}`;
  await page.goto("/sites");
  await page.getByRole("link", { name: "New site" }).click();

  // The name is suggested from the domain until you type your own
  await page.getByRole("textbox", { name: "Domain", exact: true }).fill("https://www.acme-pools.com/");
  await expect(page.getByRole("textbox", { name: "Name", exact: true })).toHaveValue("acme-pools");

  // Server-side validation shows up next to the field
  await page.getByRole("textbox", { name: "Name", exact: true }).fill(name);
  await page.getByRole("textbox", { name: "Domain", exact: true }).fill("acme-pools.com");
  await page.getByRole("button", { name: "Create site" }).click();
  await expect(page.getByText("must be a full URL")).toBeVisible();

  await page.getByRole("textbox", { name: "Domain", exact: true }).fill("https://www.acme-pools.com/");
  await page.getByLabel("Central entity").fill("swimming pool");
  await page.getByRole("button", { name: "Add section" }).click();
  await page.getByLabel("Section 1 path").fill("/pools/");
  await page.getByLabel("Section 1 name").fill("Pools");
  await page.getByLabel("Section 1 role").selectOption("core");
  await page.getByRole("button", { name: "Create site" }).click();

  // Created, selected, and listed in the switcher
  await expect(page).toHaveURL(new RegExp(`/sites/${name}\\?created=1$`));
  await expect(page.getByText("Site created and selected")).toBeVisible();
  await expect(page.getByLabel("Site", { exact: true })).toHaveValue(name);
  await expect(page.getByRole("textbox", { name: "Name", exact: true })).toBeDisabled();

  // Edit and save; the change survives a reload
  await page.getByLabel("Brand terms").fill("acme pools\nacmepools");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Saved.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Brand terms")).toHaveValue("acme pools\nacmepools");
  await expect(page.getByLabel("Section 1 path")).toHaveValue("/pools/");

  await expect(page.getByRole("link", { name: "Export YAML" })).toHaveAttribute("href", `/api/sites/${name}/export`);

  // Delete needs a second click
  await page.getByRole("button", { name: "Delete site" }).click();
  await page.getByRole("button", { name: "Yes, delete" }).click();
  await expect(page).toHaveURL(/\/sites$/);
  await expect(page.getByRole("link", { name, exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Site", { exact: true })).toHaveValue("example"); // falls back
});

test("run history can be filtered", async ({ page }) => {
  // Make sure there's at least one finished autocomplete run (cached after the first time)
  await page.goto("/tools/research/autocomplete");
  await page.getByLabel("Seed queries").fill("swimming pool");
  await page.getByLabel("Variations").selectOption("seed only");
  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByText("Suggestions", { exact: true })).toBeVisible({ timeout: 30_000 });

  await page.getByRole("link", { name: "Runs" }).click();
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
  const rows = page.locator("tbody tr");
  await expect(rows.first()).toBeVisible();

  await page.getByLabel("Status", { exact: true }).selectOption("failed");
  await page.getByLabel("Tool", { exact: true }).selectOption("research/query-fanout");
  await expect(page.getByText("No runs yet.")).toBeVisible();

  await page.getByLabel("Status", { exact: true }).selectOption("done");
  await page.getByLabel("Tool", { exact: true }).selectOption("research/autocomplete");
  await expect(rows.first()).toContainText("done");
  await rows.first().getByRole("link").click();
  await expect(page).toHaveURL(/\/tools\/research\/autocomplete\?run=/);
});

test("setup shows what's configured", async ({ page }) => {
  await page.goto("/setup");
  await expect(page.getByRole("heading", { name: "Setup" })).toBeVisible();
  const config = page.locator("section", { hasText: "Configuration" });
  await expect(config.getByText("Database", { exact: true })).toBeVisible();
  await expect(config.getByText("GEMINI_API_KEY", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Test connections" })).toBeVisible();
});
