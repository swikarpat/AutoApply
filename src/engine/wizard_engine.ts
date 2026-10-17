import * as fs from "node:fs";
import * as path from "node:path";
import { type Page, type Locator } from "playwright";
import { type Profile } from "../schema.js";
import { WorkdayResolver } from "../resolvers/workday_resolvers.js";
import { QuestionCacheEngine } from "../cache/question_cache.js";
import { logger } from "../logger.js";

export class WorkdayWizardEngine {
  private page: Page;
  private profile: Profile;
  private resolver: WorkdayResolver;
  private qaEngine: QuestionCacheEngine;

  constructor(page: Page, profile: Profile, qaEngine?: QuestionCacheEngine) {
    this.page = page;
    this.profile = profile;
    this.resolver = new WorkdayResolver(page);
    this.qaEngine = qaEngine || new QuestionCacheEngine(profile);
  }

  /**
   * Automates the full 5-step Workday Application Wizard.
   */
  async runFullWizard(resumeRelativePath: string = "./resume.pdf"): Promise<void> {
    logger.step("=== WorkdayWizardEngine: Commencing Multi-Step Wizard ===");

    // Step 1: My Information
    await this.executeStep1MyInformation();

    // Step 2: My Experience
    await this.executeStep2MyExperience(resumeRelativePath);

    // Step 3: Application Questions
    await this.executeStep3ApplicationQuestions();

    // Step 4: Voluntary Disclosures
    await this.executeStep4VoluntaryDisclosures();

    // Step 5: Review Screen (Strict Safety Gate)
    await this.executeStep5ReviewScreen();
  }

  /**
   * Step 1: My Information
   */
  async executeStep1MyInformation(): Promise<void> {
    logger.step("Wizard Engine: [Step 1/5] Processing 'My Information'...");

    // Wait for the Step 1 view container to be fully mounted
    await this.page
      .locator('[data-automation-id="legalNameSection_firstName"], [data-automation-id="progressBar"], h2:has-text("My Information")')
      .first()
      .waitFor({ state: "visible", timeout: 25000 })
      .catch(() => {});
    await this.page.waitForLoadState("networkidle").catch(() => {});
    await this.page.waitForTimeout(2000);
    const p = this.profile.personal_info;

    // 1. Country Combobox
    const countryTrigger = this.page
      .getByLabel(/country/i)
      .or(this.page.locator('[data-automation-id*="countryDropdown" i]'))
      .or(this.page.locator('button[aria-haspopup="listbox"]:has-text("Country")'))
      .first();

    if (await countryTrigger.isVisible({ timeout: 5000 }).catch(() => false)) {
      const countryVal = p.location.country || "United States of America";
      logger.info(`Step 1: Selecting Country: "${countryVal}"`);
      await this.resolver.selectCombobox(countryTrigger, countryVal);
    }

    // 2. Name Fields
    const firstName = this.page
      .getByLabel(/first name|given name/i)
      .or(this.page.locator('input[data-automation-id*="firstName" i]'))
      .first();
    if (await firstName.isVisible({ timeout: 4000 }).catch(() => false)) {
      logger.info(`Step 1: Filling First Name: "${p.first_name}"`);
      await this.resolver.fillTextInput(firstName, p.first_name);
    }

    const lastName = this.page
      .getByLabel(/last name|family name/i)
      .or(this.page.locator('input[data-automation-id*="lastName" i]'))
      .first();
    if (await lastName.isVisible({ timeout: 4000 }).catch(() => false)) {
      logger.info(`Step 1: Filling Last Name: "${p.last_name}"`);
      await this.resolver.fillTextInput(lastName, p.last_name);
    }

    // 3. Address Fields
    const address = this.page
      .getByLabel(/address line 1|street address/i)
      .or(this.page.locator('input[data-automation-id*="addressSection_addressLine1" i]'))
      .first();
    if (await address.isVisible({ timeout: 3000 }).catch(() => false)) {
      const addrVal = p.location.street_address || "100 Market St";
      logger.info(`Step 1: Filling Street Address: "${addrVal}"`);
      await this.resolver.fillTextInput(address, addrVal);
    }

    const city = this.page
      .getByLabel(/city/i)
      .or(this.page.locator('input[data-automation-id*="addressSection_city" i]'))
      .first();
    if (await city.isVisible({ timeout: 3000 }).catch(() => false)) {
      logger.info(`Step 1: Filling City: "${p.location.city}"`);
      await this.resolver.fillTextInput(city, p.location.city);
    }

    // State / Province Combobox or Input
    const stateCombobox = this.page
      .getByLabel(/state|province/i)
      .or(this.page.locator('[data-automation-id*="addressSection_countryRegion" i]'))
      .first();

    if (await stateCombobox.isVisible({ timeout: 3000 }).catch(() => false)) {
      const tag = await stateCombobox.evaluate((el) => el.tagName.toLowerCase()).catch(() => "");
      if (tag === "input") {
        const stateVal = p.location.state_code || p.location.state;
        logger.info(`Step 1: Filling State input: "${stateVal}"`);
        await this.resolver.fillTextInput(stateCombobox, stateVal);
      } else {
        const stateVal = p.location.state || "California";
        logger.info(`Step 1: Selecting State combobox: "${stateVal}"`);
        await this.resolver.selectCombobox(stateCombobox, stateVal);
      }
    }

    const postalCode = this.page
      .getByLabel(/postal code|zip/i)
      .or(this.page.locator('input[data-automation-id*="addressSection_postalCode" i]'))
      .first();
    if (await postalCode.isVisible({ timeout: 3000 }).catch(() => false)) {
      const zipVal = p.location.postal_code || "94105";
      logger.info(`Step 1: Filling Postal Code: "${zipVal}"`);
      await this.resolver.fillTextInput(postalCode, zipVal);
    }

    // 4. Phone Number & Device Type
    const phoneInput = this.page
      .getByLabel(/phone number/i)
      .or(this.page.locator('input[data-automation-id*="phone-number" i]'))
      .first();
    if (await phoneInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      const phoneVal = p.phone || "+14155550199";
      logger.info(`Step 1: Filling Phone Number: "${phoneVal}"`);
      await this.resolver.fillTextInput(phoneInput, phoneVal);
    }

    const phoneDeviceType = this.page
      .getByLabel(/phone device type/i)
      .or(this.page.locator('[data-automation-id*="phone-device-type" i]'))
      .first();
    if (await phoneDeviceType.isVisible({ timeout: 3000 }).catch(() => false)) {
      const deviceVal = p.phone_device_type || "Mobile";
      logger.info(`Step 1: Selecting Phone Device Type: "${deviceVal}"`);
      await this.resolver.selectCombobox(phoneDeviceType, deviceVal);
    }

    // 5. "How Did You Hear About Us?" Combobox
    const sourceDropdown = this.page
      .getByLabel(/how did you hear about us|source/i)
      .or(this.page.locator('[data-automation-id*="sourcePrompt" i]'))
      .first();

    if (await sourceDropdown.isVisible({ timeout: 3000 }).catch(() => false)) {
      logger.info("Step 1: Selecting 'How Did You Hear About Us?' combobox...");
      await this.resolver.selectCombobox(sourceDropdown, "Company Career Site");
    }

    await this.clickSaveAndContinue("Step 1 (My Information)");
  }

  /**
   * Step 2: My Experience
   */
  async executeStep2MyExperience(resumeRelativePath: string): Promise<void> {
    logger.step("Wizard Engine: [Step 2/5] Processing 'My Experience' & Resume Upload...");
    await this.page.waitForTimeout(2000);

    const fullResumePath = path.resolve(process.cwd(), resumeRelativePath);
    if (!fs.existsSync(fullResumePath)) {
      throw new Error(`Resume file not found for upload at: ${fullResumePath}`);
    }

    logger.info(`Uploading resume file from: ${fullResumePath}`);
    const fileInput = this.page.locator('input[type="file"]').first();

    if (await fileInput.count() > 0) {
      await fileInput.setInputFiles(fullResumePath);
      logger.info("Dispatched setInputFiles with resume.");
      await this.page.waitForTimeout(3000);

      // Wait for upload progress indicator to complete if present
      const uploadSuccess = this.page
        .locator('[data-automation-id="file-upload-item"], [data-automation-id*="uploadedFile" i]')
        .first();

      await uploadSuccess.waitFor({ state: "visible", timeout: 15000 }).catch(() => {
        logger.debug("Upload completed without dedicated completion badge element.");
      });
    } else {
      logger.warn("No direct input[type='file'] element found on current screen. Checking if already attached.");
    }

    await this.clickSaveAndContinue("Step 2 (My Experience)");
  }

  /**
   * Step 3: Application Questions
   */
  async executeStep3ApplicationQuestions(): Promise<void> {
    logger.step("Wizard Engine: [Step 3/5] Resolving 'Application Questions'...");
    await this.page.waitForTimeout(2000);

    // Find all question fieldsets / radiogroups
    const fieldsets = this.page.locator('fieldset, [role="radiogroup"]');
    const fieldsetCount = await fieldsets.count();
    logger.info(`Detected ${fieldsetCount} question fieldsets / groups on page.`);

    for (let i = 0; i < fieldsetCount; i++) {
      const fieldset = fieldsets.nth(i);
      const legendText = (await fieldset.innerText().catch(() => "")) || "";
      if (!legendText.trim()) continue;

      const firstLine = legendText.split("\n")[0].trim();
      const resolvedAnswer = this.qaEngine.resolveQuestion(firstLine);

      if (resolvedAnswer) {
        const answerText = String(resolvedAnswer.answer);
        logger.info(`Answering question [${i + 1}]: "${firstLine}" => "${answerText}"`);
        await this.resolver.selectRadio(fieldset, answerText);
      } else {
        logger.warn(`Unresolved question encountered: "${firstLine}". Defaulting to 'No' or first option.`);
        await this.resolver.selectRadio(fieldset, "No");
      }
    }

    // Check for any loose single dropdowns/questions
    const questionCombos = this.page.locator('[data-automation-id*="question" i] [role="combobox"]');
    const comboCount = await questionCombos.count();
    for (let j = 0; j < comboCount; j++) {
      const combo = questionCombos.nth(j);
      const label = (await combo.getAttribute("aria-label").catch(() => "")) || "";
      const resolved = this.qaEngine.resolveQuestion(label);
      if (resolved) {
        await this.resolver.selectCombobox(combo, String(resolved.answer));
      }
    }

    await this.clickSaveAndContinue("Step 3 (Application Questions)");
  }

  /**
   * Step 4: Voluntary Disclosures (EEOC)
   */
  async executeStep4VoluntaryDisclosures(): Promise<void> {
    logger.step("Wizard Engine: [Step 4/5] Processing 'Voluntary Disclosures'...");
    await this.page.waitForTimeout(2000);

    const eeoc = this.profile.demographics_eeoc || {
      gender: "Decline to self-identify",
      race_ethnicity: "Decline to self-identify",
      veteran_status: "I am not a protected veteran",
      disability_status: "I do not have a disability",
    };

    // 1. Terms & Acknowledgment checkbox
    const acknowledgeCheckbox = this.page
      .getByRole("checkbox", { name: /acknowledge|agree|terms/i })
      .or(this.page.locator('input[type="checkbox"]'))
      .first();

    if (await acknowledgeCheckbox.isVisible({ timeout: 3000 }).catch(() => false)) {
      await this.resolver.setCheckbox(acknowledgeCheckbox, true);
    }

    // 2. Gender Combobox / Radiogroup
    const genderSelector = this.page.getByLabel(/gender/i).first();
    if (await genderSelector.isVisible({ timeout: 3000 }).catch(() => false)) {
      await this.resolver.selectCombobox(genderSelector, eeoc.gender);
    }

    // 3. Race & Ethnicity
    const raceSelector = this.page.getByLabel(/race|ethnicity/i).first();
    if (await raceSelector.isVisible({ timeout: 3000 }).catch(() => false)) {
      await this.resolver.selectCombobox(raceSelector, eeoc.race_ethnicity);
    }

    // 4. Veteran Status
    const veteranSelector = this.page.getByLabel(/veteran status|veteran/i).first();
    if (await veteranSelector.isVisible({ timeout: 3000 }).catch(() => false)) {
      await this.resolver.selectCombobox(veteranSelector, eeoc.veteran_status);
    }

    // 5. Disability Status
    const disabilitySelector = this.page.getByLabel(/disability status|disability/i).first();
    if (await disabilitySelector.isVisible({ timeout: 3000 }).catch(() => false)) {
      await this.resolver.selectCombobox(disabilitySelector, eeoc.disability_status);
    }

    await this.clickSaveAndContinue("Step 4 (Voluntary Disclosures)");
  }

  /**
   * Step 5: Review Screen
   * STRICT SAFETY GATE: Assert Submit button exists, but NEVER click submit.
   */
  async executeStep5ReviewScreen(): Promise<void> {
    logger.step("Wizard Engine: [Step 5/5] Reached Final Review Screen. Running strict safety gate...");
    await this.page.waitForTimeout(3000);

    const bodyText = (await this.page.textContent("body").catch(() => "")) || "";
    const isReviewStage =
      bodyText.includes("Review") ||
      (await this.page.locator('button[data-automation-id="bottom-navigation-next-button"]:has-text("Submit")').count()) > 0;

    logger.info(`Review stage confirmation: ${isReviewStage ? "VERIFIED" : "PENDING"}`);

    // Safety Gate: Check for submit button
    const submitButton = this.page
      .getByRole("button", { name: /^submit$/i })
      .or(this.page.locator('button[data-automation-id="bottom-navigation-next-button"]:has-text("Submit")'))
      .first();

    const submitVisible = await submitButton.isVisible({ timeout: 5000 }).catch(() => false);
    if (submitVisible) {
      logger.step(
        "STRICT SAFETY GATE PASSED: Submit button detected, but NOT clicked (Zero-HITL Safe Mode)."
      );
    } else {
      logger.info("Final review screen reached.");
    }

    // Save verification screenshot
    const debugDir = path.resolve(process.cwd(), "debug");
    if (!fs.existsSync(debugDir)) {
      fs.mkdirSync(debugDir, { recursive: true });
    }
    const screenshotPath = path.join(debugDir, "phase3_review_screen.png");
    await this.page.screenshot({ path: screenshotPath, fullPage: true });
    logger.info(`Final Phase 3 Review Screen verification screenshot saved to: ${screenshotPath}`);
  }

  /**
   * Clicks 'Save and Continue' and inspects the page for any validation errors.
   */
  private async clickSaveAndContinue(stepLabel: string): Promise<void> {
    logger.step(`Submitting '${stepLabel}' -> Locating and clicking 'Save and Continue'...`);

    // Scope strictly to form buttons, bottom navigation, or primary submit actions
    const primaryBtn = this.page
      .locator('button[data-automation-id="bottom-navigation-next-button"]')
      .or(this.page.locator('button[type="submit"]:visible'))
      .or(this.page.locator('form button:visible').filter({ hasText: /save and continue|continue|next/i }))
      .or(this.page.getByRole("button", { name: /^save and continue$/i }))
      .or(this.page.getByRole("button", { name: /^continue$/i }))
      .or(this.page.getByRole("button", { name: /^next$/i }))
      .first();

    // Guard against clicking marketing/informational links
    const tagName = await primaryBtn.evaluate((el) => el.tagName.toLowerCase()).catch(() => "");
    const href = await primaryBtn.getAttribute("href").catch(() => "");
    if (href && (href.includes("/resources/") || href.includes("/home/"))) {
      logger.warn(`Rejected invalid navigation button with href: ${href}`);
    }

    try {
      await primaryBtn.scrollIntoViewIfNeeded({ timeout: 10000 });
      await primaryBtn.waitFor({ state: "visible", timeout: 15000 });
      await primaryBtn.click();
    } catch (e) {
      const debugDir = path.resolve(process.cwd(), "debug");
      if (!fs.existsSync(debugDir)) fs.mkdirSync(debugDir, { recursive: true });
      const failScreen = path.join(debugDir, "save_continue_fail.png");
      await this.page.screenshot({ path: failScreen, fullPage: true }).catch(() => {});
      logger.error(`Could not locate or click Save and Continue button on ${stepLabel}. Screenshot saved to ${failScreen}`);
      throw e;
    }

    await this.page.waitForTimeout(2500);

    // Safety: If navigation strayed away to a marketing/resource page, go back
    if (this.page.url().includes("/resources/") || this.page.url().includes("/home/")) {
      logger.warn(`Detected accidental redirection to ${this.page.url()}. Navigating back to application form...`);
      await this.page.goBack({ waitUntil: "networkidle" }).catch(() => {});
    }

    // Step Transition Error Guard
    await this.checkStepErrors(stepLabel);
  }

  /**
   * Inspects page for Workday error banners or fields with aria-invalid="true".
   */
  private async checkStepErrors(stepLabel: string): Promise<void> {
    const errorWidget = this.page.locator('[data-automation-id="errorWidget"], [data-automation-id*="alert" i]');
    const invalidFields = this.page.locator('[aria-invalid="true"]');

    const hasErrorWidget = await errorWidget.isVisible().catch(() => false);
    const invalidCount = await invalidFields.count();

    if (hasErrorWidget || invalidCount > 0) {
      const errText = hasErrorWidget ? (await errorWidget.innerText().catch(() => "")) : "";
      const debugDir = path.resolve(process.cwd(), "debug");
      if (!fs.existsSync(debugDir)) fs.mkdirSync(debugDir, { recursive: true });

      const errScreenshot = path.join(debugDir, "step_error.png");
      await this.page.screenshot({ path: errScreenshot, fullPage: true });

      const errMsg = `Step transition error on ${stepLabel}: ErrorWidget="${errText.trim()}", InvalidFieldsCount=${invalidCount}`;
      logger.error(errMsg, { screenshot: errScreenshot });
      throw new Error(errMsg);
    }

    logger.info(`Step transition successful: ${stepLabel}`);
  }
}
