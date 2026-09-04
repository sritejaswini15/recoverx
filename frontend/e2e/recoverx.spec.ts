import { expect, test, type Page } from "@playwright/test";

const credentials = {
  email: process.env.RECOVERX_E2E_EMAIL ?? "admin@recoverx.local",
  password: process.env.RECOVERX_E2E_PASSWORD ?? "recoverx-demo",
};

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(credentials.email);
  await page.getByLabel("Password").fill(credentials.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForFunction(() => Boolean(window.localStorage.getItem("recoverx_access_token")));
  await page.goto("/");
  await expect(page).toHaveURL(/\/$/);
  const token = await page.evaluate(() => window.localStorage.getItem("recoverx_access_token"));
  const apiUrl = process.env.PLAYWRIGHT_API_URL ?? "http://127.0.0.1:8000";
  const seedResponse = await page.request.post(`${apiUrl}/demo/reset`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { customers: 1000, cases: 500, seed: 20260902 },
  });
  expect(seedResponse.ok()).toBeTruthy();
}

test("login and dashboard load", async ({ page }) => {
  await login(page);
  await expect(page.getByText("Command center").first()).toBeVisible();
  await expect(page.getByText(/Revenue at risk/i).first()).toBeVisible();
});

test("cases and investigation route load", async ({ page }) => {
  await login(page);
  await page.goto("/cases");
  await expect(page.getByRole("heading", { name: /case queue/i })).toBeVisible();
  const firstCase = page.locator('a[href^="/cases/"]').first();
  await expect(firstCase).toBeVisible();
  await firstCase.click();
  await expect(page.getByText(/AI diagnosis/i)).toBeVisible();
});

test("simulation center exposes real recovery controls", async ({ page }) => {
  await login(page);
  await page.goto("/simulator");
  await expect(page.getByRole("heading", { name: /RecoverX Simulation Center/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Trigger event/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Pay now/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /provider timeout/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /low AI confidence/i })).toBeVisible();
});
