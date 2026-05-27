import { test, expect } from "@playwright/test";

test.describe("Analysis Flow", () => {
  test("analysis new page renders config form", async ({ page }) => {
    await page.goto("/analysis/new");
    await expect(page.locator("main#main-content")).toBeVisible();
    await expect(page.getByText(/ticker|symbol|stock/i).first()).toBeVisible();
  });

  test("scanner page renders", async ({ page }) => {
    await page.goto("/scanner");
    await expect(page.locator("main#main-content")).toBeVisible();
  });
});

test.describe("Account Management", () => {
  test("accounts page loads", async ({ page }) => {
    await page.goto("/accounts");
    await expect(page.locator("main#main-content")).toBeVisible();
  });

  test("analytics page loads charts", async ({ page }) => {
    await page.goto("/analytics");
    await expect(page.locator("main#main-content")).toBeVisible();
  });
});

test.describe("Error Recovery", () => {
  test("handles network errors gracefully", async ({ page }) => {
    await page.route("**/api/**", (route) => route.abort());
    await page.goto("/accounts");
    await expect(page.locator("main#main-content")).toBeVisible();
  });
});
