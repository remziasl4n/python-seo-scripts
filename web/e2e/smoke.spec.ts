import { expect, test } from "@playwright/test";

// One real autocomplete request to Google (seed only); later runs come from the cache.

test("overview shows the site, the tools and recent runs", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "SEO Toolkit" })).toBeVisible();
  await expect(page.getByLabel("Site")).toHaveValue("example");
  await expect(page.getByText("swimming pool", { exact: true })).toBeVisible();
  const sidebar = page.getByRole("complementary");
  await expect(sidebar.getByRole("link", { name: "Autocomplete" })).toBeVisible();
  await expect(sidebar.getByRole("link", { name: "Query fan-out" })).toBeVisible();
});

test("a tool runs in the background and shows sortable, filterable results", async ({ page }) => {
  await page.goto("/tools/research/autocomplete");
  await expect(page.getByRole("heading", { name: "Autocomplete" })).toBeVisible();

  await page.getByLabel("Seed queries").fill("swimming pool");
  await page.getByLabel("Variations").selectOption("seed only");
  await page.getByRole("button", { name: "Run" }).click();

  // The run id goes into the URL, so a refresh shows the same run
  await expect(page).toHaveURL(/\?run=\d{8}-\d{6}-[0-9a-f]{6}/);
  await expect(page.getByText("done", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Suggestions", { exact: true })).toBeVisible();

  const rows = page.locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  const total = await rows.count();
  expect(total).toBeGreaterThan(1);

  // Sorting: the best_position column sorts high-to-low first for numbers
  await page.getByRole("button", { name: "best position" }).click();
  await expect(page.locator("th[aria-sort='descending']")).toHaveCount(1);

  // Filtering
  await page.getByLabel("Filter rows").fill("zzzz-no-match");
  await expect(page.getByText("No rows match the filter.")).toBeVisible();
  await page.getByLabel("Filter rows").fill("");

  // Downloads point at the API
  await expect(page.getByRole("link", { name: "CSV" })).toHaveAttribute("href", /\/download\?format=csv$/);

  // A reload brings back the same finished run
  await page.reload();
  await expect(page.getByText("Suggestions", { exact: true })).toBeVisible();
  await expect(page.locator("tbody tr").first()).toBeVisible();
});

test("invalid inputs are shown next to the field", async ({ page }) => {
  await page.goto("/tools/research/autocomplete");
  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByText("List should have at least 1 item after validation")).toBeVisible();
  await expect(page).not.toHaveURL(/\?run=/);
});

test("forms are generated from each tool's schema", async ({ page }) => {
  await page.goto("/tools/research/query-fanout");
  await expect(page.getByLabel("Seed query or entity")).toBeVisible();
  await expect(page.getByLabel("Queries per fan-out type")).toHaveValue("6");
  await expect(page.getByLabel("Record Gemini's real searches")).toBeChecked();
  await expect(page.getByLabel("Check against autocomplete")).toBeChecked();
});

test("dark mode is remembered", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("radio", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
});
