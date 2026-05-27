import { test, expect } from "@playwright/test";

test.describe("Navigation", () => {
  test("loads homepage with sidebar", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/TradingAgents/i);
    await expect(page.locator("main#main-content")).toBeVisible();
  });

  test("navigates to analysis page", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: /analysis|scan/i }).first().click();
    await expect(page).toHaveURL(/\/(analysis|scanner)/);
  });

  test("navigates to accounts page", async ({ page }) => {
    await page.goto("/accounts");
    await expect(page.locator("main#main-content")).toBeVisible();
  });

  test("navigates to trades page", async ({ page }) => {
    await page.goto("/trades");
    await expect(page.locator("main#main-content")).toBeVisible();
  });

  test("navigates to strategies page", async ({ page }) => {
    await page.goto("/strategies");
    await expect(page.locator("main#main-content")).toBeVisible();
  });

  test("shows 404 for unknown route", async ({ page }) => {
    await page.goto("/this-does-not-exist");
    await expect(page.getByText(/not found|404/i)).toBeVisible();
  });
});

test.describe("Accessibility", () => {
  test("skip-to-content link works", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    const skipLink = page.getByText("Skip to content");
    await expect(skipLink).toBeFocused();
  });

  test("main content has proper landmark", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("main")).toHaveAttribute("id", "main-content");
  });
});
