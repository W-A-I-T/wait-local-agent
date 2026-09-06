import { randomUUID } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { api, expect, signIn, test } from "./helpers";

for (const [width, height] of [[1440, 900], [1024, 768], [768, 1024], [390, 844]]) {
  test(`onboarding and client setup remain usable with keyboard at ${width}x${height}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height });
    await signIn(page, undefined, false);
    const dialog = page.getByRole("dialog", { name: "Set up your MSP operations" });
    await expect(dialog).toBeVisible();
    expect.soft((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze()).violations).toEqual([]);
    expect.soft(await dialog.getByRole("list", { name: "Onboarding progress" }).getByRole("button").evaluateAll((steps) => steps.every((step) => step.scrollWidth <= step.clientWidth + 1)), "Wizard step text must fit its own control").toBe(true);
    await testInfo.attach(`onboarding-${width}x${height}`, { body: await page.screenshot(), contentType: "image/png" });
    await expect(dialog.getByRole("button", { name: "Dismiss", exact: true })).toBeFocused();
    // Native dialogs may move focus to browser chrome at the document boundary.
    // Exercise traversal within the dialog and verify the page behind it is inert.
    await page.keyboard.press("Tab");
    await expect(dialog.getByRole("button", { name: "Create a client", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(dialog.getByRole("link", { name: "Open client configuration" })).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    await expect(dialog.getByRole("button", { name: "Create a client", exact: true })).toBeFocused();
    await page.locator(".client-selector select").evaluate((element) => (element as HTMLSelectElement).focus());
    await expect(dialog.getByRole("button", { name: "Create a client", exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await page.getByRole("link", { name: "Clients", exact: true }).click();
    await page.getByRole("button", { name: "New client", exact: true }).click();
    const name = `Client Alpha ${"long-name-".repeat(7)} ${randomUUID()}`;
    await page.getByLabel("Client ID", { exact: true }).fill(`responsive-${randomUUID()}`);
    await page.getByLabel("Name", { exact: true }).fill(name);
    await page.getByRole("button", { name: "Create client", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Client created." })).toBeVisible();
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
      if (path === "/system/diagnostics") {
        const flags = page.getByLabel("Safe feature configuration");
        await expect(flags.getByRole("term")).toHaveCount(8);
        await expect(flags.getByText("Not connected", { exact: true })).toHaveCount(0);
        expect(await flags.getByRole("term").evaluateAll((terms) => terms.every((term) => {
          const value = term.nextElementSibling;
          return value !== null && value.getBoundingClientRect().top >= term.getBoundingClientRect().bottom;
        })), "Feature values must not overlap their labels").toBe(true);
      }
      const layout = await page.evaluate(() => ({
        width: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
        overflow: [...document.querySelectorAll(".workspace *")].filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
          .slice(0, 30).map((element) => ({ tag: element.tagName, className: element.className, width: element.getBoundingClientRect().width })),
      }));
      expect.soft(layout.width, `${path} overflow: ${JSON.stringify(layout.overflow)}`).toBeLessThanOrEqual(layout.viewport + 1);
      const unnamed = await page.getByRole("button").evaluateAll((buttons) => buttons
        .filter((button) => !(button.textContent?.trim() || button.getAttribute("aria-label") || button.getAttribute("aria-labelledby")))
        .map((button) => button.outerHTML));
      expect.soft(unnamed, `${path} buttons need accessible names`).toEqual([]);
      const accessibility = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      expect.soft(accessibility.violations, `${path} accessibility violations`).toEqual([]);
      await testInfo.attach(`${path.replaceAll("/", "-")}-${width}x${height}`, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
    }
  });
}
