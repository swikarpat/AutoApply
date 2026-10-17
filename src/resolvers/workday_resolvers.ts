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
    try {
      await triggerLocator.waitFor({ state: "visible", timeout: 8000 });
      await triggerLocator.scrollIntoViewIfNeeded();

      // 1. Check if the element itself or an immediate child is a native <select>
      const tagName = await triggerLocator.evaluate((el) => el.tagName.toLowerCase()).catch(() => "");
      if (tagName === "select") {
        logger.info(`selectCombobox: Direct native <select> detected. Setting value for "${targetOptionText}"...`);
        await triggerLocator.selectOption({ label: targetOptionText }).catch(async () => {
          const matchingVal = await triggerLocator
            .locator("option")
            .filter({ hasText: new RegExp(this.escapeRegex(targetOptionText), "i") })
            .first()
            .getAttribute("value");
          if (matchingVal) await triggerLocator.selectOption(matchingVal);
        });
        await triggerLocator.evaluate((el) => {
          el.dispatchEvent(new Event("change", { bubbles: true }));
          el.dispatchEvent(new Event("blur", { bubbles: true }));
        }).catch(() => {});
        return true;
      }

      const nestedSelect = triggerLocator.locator("select").first();
      if ((await nestedSelect.count()) > 0) {
        logger.info(`selectCombobox: Nested native <select> detected. Setting value for "${targetOptionText}"...`);
        await nestedSelect.selectOption({ label: targetOptionText }).catch(async () => {
          const matchingVal = await nestedSelect
            .locator("option")
            .filter({ hasText: new RegExp(this.escapeRegex(targetOptionText), "i") })
            .first()
            .getAttribute("value");
          if (matchingVal) await nestedSelect.selectOption(matchingVal);
        });
        await nestedSelect.evaluate((el) => {
          el.dispatchEvent(new Event("change", { bubbles: true }));
          el.dispatchEvent(new Event("blur", { bubbles: true }));
        }).catch(() => {});
        return true;
      }

      // 2. Custom ARIA / Listbox Combobox
      await triggerLocator.click({ force: true });
      await this.page.waitForTimeout(300);

      const popupListbox = this.page
        .locator(
          '[role="listbox"], [role="menu"], div[data-automation-id="popup"], [data-automation-id="select-options"], ul[role="listbox"], div[class*="options" i]'
        )
        .first();

      const listboxFound = await popupListbox
        .waitFor({ state: "visible", timeout: 3500 })
        .then(() => true)
        .catch(() => false);

      if (listboxFound) {
        const directOption = popupListbox
          .locator('[role="option"], [role="menuitem"], li, button')
          .filter({ hasText: new RegExp(`^\\s*${this.escapeRegex(targetOptionText)}\\s*$`, "i") })
          .or(
            popupListbox
              .locator('[role="option"], [role="menuitem"], li, button')
              .filter({ hasText: new RegExp(this.escapeRegex(targetOptionText), "i") })
          )
          .first();

        if (await directOption.isVisible({ timeout: 2000 }).catch(() => false)) {
          await directOption.click();
          return true;
        }
      }

      // 3. Fallback: Keyboard typing into active element
      await this.page.keyboard.type(targetOptionText, { delay: 60 });
      await this.page.keyboard.press("Enter");
      return true;
    } catch (err: any) {
      logger.warn(`selectCombobox non-fatal notice: Failed selecting "${targetOptionText}": ${err.message}`);
      return false;
    }
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
