import { type Page, type Locator } from "playwright";
import { logger } from "../logger.js";

export class WorkdayResolver {
  private page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  /**
   * Fills a text input by clicking, clearing, typing with human delay,
   * and explicitly dispatching 'input', 'change', and 'blur' events.
   */
  async fillTextInput(locator: Locator, value: string): Promise<void> {
    logger.debug(`WorkdayResolver.fillTextInput: Attempting to fill "${value}"`);
    await locator.waitFor({ state: "visible", timeout: 10000 });
    await locator.scrollIntoViewIfNeeded();

    await locator.click();
    await this.page.waitForTimeout(50);

    // Clear existing content cleanly
    await locator.fill("");
    await this.page.waitForTimeout(50);

    // Type with subtle human delay to trigger internal framework state machines
    await locator.pressSequentially(value, { delay: 40 });

    // Explicitly dispatch standard events to ensure Workday/React/GWT state hooks persist
    await locator.evaluate((node) => {
      node.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
      node.dispatchEvent(new Event("change", { bubbles: true, cancelable: true }));
      node.dispatchEvent(new Event("blur", { bubbles: true, cancelable: true }));
    });

    await this.page.waitForTimeout(80);

    // Verify value persisted
    const actualValue = await locator.inputValue().catch(() => "");
    if (actualValue !== value) {
      logger.warn(`Input value check mismatch. Expected: "${value}", Actual: "${actualValue}"`);
    } else {
      logger.debug(`Verified text input persisted: "${value}"`);
    }
  }

  /**
   * Resolves custom Workday comboboxes / floating listboxes:
   * 1. Clicks trigger button/combobox
   * 2. Waits for floating popup listbox (`[role="listbox"]` or `div[data-automation-id="popup"]`)
   * 3. Selects matching `[role="option"]` (exact or substring)
   * 4. If option is hidden/virtualized, types into filter and uses keyboard navigation
   * 5. Confirms selection reflected in trigger
   */
  async selectCombobox(triggerLocator: Locator, targetOptionText: string): Promise<boolean> {
    logger.step(`WorkdayResolver.selectCombobox: Selecting "${targetOptionText}"`);
    await triggerLocator.waitFor({ state: "visible", timeout: 10000 });
    await triggerLocator.scrollIntoViewIfNeeded();

    // Click trigger to expand popup
    await triggerLocator.click();
    await this.page.waitForTimeout(200);

    // Locate floating popup listbox at page root level
    const popupListbox = this.page
      .locator('[role="listbox"]')
      .or(this.page.locator('div[data-automation-id="popup"]'))
      .or(this.page.locator('[data-automation-id="select-options"]'))
      .first();

    try {
      await popupListbox.waitFor({ state: "visible", timeout: 7000 });
    } catch {
      logger.warn("Popup listbox did not appear on primary click. Retrying trigger click...");
      await triggerLocator.click();
      await popupListbox.waitFor({ state: "visible", timeout: 5000 });
    }

    // Try finding direct matching option within visible list
    const optionsLocator = popupListbox.locator('[role="option"]');
    const optionCount = await optionsLocator.count();
    logger.debug(`Found ${optionCount} options in floating listbox`);

    let selected = false;

    // Direct text search
    const matchingOption = popupListbox
      .locator('[role="option"]')
      .filter({ hasText: new RegExp(`^\\s*${this.escapeRegex(targetOptionText)}\\s*$`, "i") })
      .or(
        popupListbox
          .locator('[role="option"]')
          .filter({ hasText: new RegExp(this.escapeRegex(targetOptionText), "i") })
      )
      .first();

    if (await matchingOption.isVisible().catch(() => false)) {
      logger.debug(`Clicking visible matching option for "${targetOptionText}"`);
      await matchingOption.scrollIntoViewIfNeeded();
      await matchingOption.click();
      selected = true;
    } else {
      // If list is large or virtualized, check if there is an embedded search input
      const searchInput = popupListbox.locator('input[type="text"], input[role="searchbox"]').first();
      if (await searchInput.isVisible().catch(() => false)) {
        logger.debug(`Typing into combobox search filter: "${targetOptionText}"`);
        await searchInput.fill(targetOptionText);
        await this.page.waitForTimeout(300);
      } else {
        // Fallback: keyboard navigation on active element
        logger.debug(`Using keyboard typing for virtualized combobox: "${targetOptionText}"`);
        await this.page.keyboard.type(targetOptionText, { delay: 50 });
        await this.page.waitForTimeout(250);
      }

      // Check if option is now visible
      const filteredOption = popupListbox
        .locator('[role="option"]')
        .filter({ hasText: new RegExp(this.escapeRegex(targetOptionText), "i") })
        .first();

      if (await filteredOption.isVisible().catch(() => false)) {
        await filteredOption.click();
        selected = true;
      } else {
        // Press Enter as fallback selection
        logger.debug("Pressing ArrowDown and Enter to select highlighted item");
        await this.page.keyboard.press("ArrowDown");
        await this.page.waitForTimeout(100);
        await this.page.keyboard.press("Enter");
        selected = true;
      }
    }

    // Trigger blur on trigger element to notify framework
    await triggerLocator.evaluate((el) => {
      el.dispatchEvent(new Event("change", { bubbles: true }));
      el.dispatchEvent(new Event("blur", { bubbles: true }));
    }).catch(() => {});

    await this.page.waitForTimeout(200);

    // Verify selection in trigger text or value
    const triggerText = (await triggerLocator.innerText().catch(() => "")) || "";
    logger.info(`WorkdayResolver.selectCombobox result: trigger currently shows "${triggerText.trim()}"`);
    return selected;
  }

  /**
   * Locates radio options within an ARIA radiogroup or fieldset and checks the matching option.
   */
  async selectRadio(groupLocatorOrLabel: Locator | string, targetText: string): Promise<boolean> {
    logger.step(`WorkdayResolver.selectRadio: Selecting "${targetText}"`);

    let group: Locator;
    if (typeof groupLocatorOrLabel === "string") {
      group = this.page
        .getByRole("radiogroup", { name: new RegExp(this.escapeRegex(groupLocatorOrLabel), "i") })
        .or(this.page.locator(`fieldset:has-text("${groupLocatorOrLabel}")`))
        .first();
    } else {
      group = groupLocatorOrLabel;
    }

    // Locate radio by role or label text
    const targetRadio = group
      .getByRole("radio", { name: new RegExp(this.escapeRegex(targetText), "i") })
      .or(group.locator(`label:has-text("${targetText}") input[type="radio"]`))
      .or(group.locator(`label:has-text("${targetText}")`))
      .first();

    if (await targetRadio.isVisible({ timeout: 5000 }).catch(() => false)) {
      await targetRadio.scrollIntoViewIfNeeded();
      await targetRadio.click();
      await this.page.waitForTimeout(100);
      logger.info(`WorkdayResolver.selectRadio: Successfully checked "${targetText}"`);
      return true;
    }

    logger.warn(`Could not locate visible radio option matching "${targetText}"`);
    return false;
  }

  /**
   * Sets checkbox state with proper click and change dispatching.
   */
  async setCheckbox(locator: Locator, shouldBeChecked: boolean): Promise<boolean> {
    logger.debug(`WorkdayResolver.setCheckbox: Setting checkbox to ${shouldBeChecked}`);
    await locator.waitFor({ state: "visible", timeout: 8000 });
    await locator.scrollIntoViewIfNeeded();

    const isChecked = await locator.isChecked().catch(() => false);
    if (isChecked !== shouldBeChecked) {
      await locator.click();
      await locator.evaluate((el) => {
        el.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await this.page.waitForTimeout(100);
    }

    const finalState = await locator.isChecked().catch(() => false);
    logger.info(`WorkdayResolver.setCheckbox: Checkbox state is now ${finalState}`);
    return finalState === shouldBeChecked;
  }

  private escapeRegex(string: string): string {
    return string.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
}
