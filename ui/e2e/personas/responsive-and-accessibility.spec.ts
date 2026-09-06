import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { api, expect, signIn, test } from "./helpers";

for (const [width, height] of [[1440, 900], [1024, 768], [768, 1024], [390, 844]]) {
  test(`onboarding and client setup remain usable with keyboard at ${width}x${height}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height });
    await signIn(page, undefined, false);
    const dialog = page.getByRole("dialog", { name: "Set up your MSP operations" });
    await expect(dialog).toBeVisible();
    expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze()).violations).toEqual([]);
    await expect(dialog.getByRole("button", { name: "Dismiss", exact: true })).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await page.getByRole("link", { name: "Clients", exact: true }).click();
    await page.getByRole("button", { name: "New client", exact: true }).click();
    const name = `Client Alpha ${"long-name-".repeat(7)} ${randomUUID()}`;
    await page.getByLabel("Client ID", { exact: true }).fill(`responsive-${randomUUID()}`);
    await page.getByLabel("Name", { exact: true }).fill(name);
    await page.getByRole("button", { name: "Create client", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Client created.");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    const client = page.getByRole("combobox", { name: "Client", exact: true });
    await expect(client).toBeVisible();
    const box = await client.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
    await testInfo.attach(`clients-${width}x${height}`, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
  });

  test(`critical operational and requester screens fit ${width}x${height}`, async ({ page, request }, testInfo) => {
    await page.setViewportSize({ width, height });
    await signIn(page);
    const id = `viewport-${randomUUID()}`;
    await api(request, "/clients", { client_id: id, name: `Client Beta ${"very-long-name-".repeat(6)}` });
    await page.reload();
    await page.getByRole("combobox", { name: "Client", exact: true }).selectOption(id);
    for (const [path, heading] of [
      ["/approvals", "Approval Queue"], ["/system/diagnostics", "Diagnostics & Support"],
      ["/technician-chat", "Technician Chat"], ["/consultant", "Solutions Architect"],
      ["/founder", "Prepare your Launch Passport upload"], ["/end-user", "How can we help?"],
    ]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), path).toBe(true);
      const unnamed = await page.getByRole("button").evaluateAll((buttons) => buttons
        .filter((button) => !(button.textContent?.trim() || button.getAttribute("aria-label") || button.getAttribute("aria-labelledby")))
        .map((button) => button.outerHTML));
      expect(unnamed, `${path} buttons need accessible names`).toEqual([]);
      const accessibility = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect(accessibility.violations, `${path} accessibility violations`).toEqual([]);
      await testInfo.attach(`${path.replaceAll("/", "-")}-${width}x${height}`, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
    }
  });
}
