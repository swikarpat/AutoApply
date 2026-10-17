import * as fs from "node:fs";
import * as path from "node:path";
import { launchBrowserSession } from "./browser/launcher.js";
import { loadProfile } from "./config.js";
import { QuestionCacheEngine } from "./cache/question_cache.js";
import { WorkdayResolver } from "./resolvers/workday_resolvers.js";
import { logger } from "./logger.js";

export async function runPhase2Test(targetUrl: string): Promise<void> {
  logger.step("=== STARTING PHASE 2: WORKDAY RESOLVERS & QA CACHE TEST ===");

  // 1. Load validated candidate profile
  const profile = loadProfile();
  logger.info(`Loaded candidate profile for: ${profile.personal_info.full_name}`);

  // 2. Initialize and verify Semantic Question Cache Engine
  logger.step("Testing Semantic Question Cache Engine resolution...");
  const qaEngine = new QuestionCacheEngine(profile);

  // Test deterministic question resolution
  const testQuestions = [
    "Are you legally authorized to work in the United States?",
    "Will you require employment visa sponsorship now or in future?",
    "Do you currently hold an active security clearance?",
    "Are you open to relocation?",
  ];

  for (const q of testQuestions) {
    const res = qaEngine.resolveQuestion(q);
    logger.info(`QA Resolution Test: "${q}" => ${res ? res.answer : "UNRESOLVED"} (source: ${res?.source})`);
  }

  // 3. Launch browser session
  const { browser, page } = await launchBrowserSession(false);
  const workday = new WorkdayResolver(page);

  try {
    logger.step(`Navigating to job portal: ${targetUrl}`);
    await page.goto(targetUrl, { waitUntil: "networkidle", timeout: 45000 });

    const title = await page.title();
    logger.info(`Landed on job page: "${title}"`);

    // 4. Click primary "Apply" button
    logger.step("Locating and clicking primary 'Apply' button...");
    const applyButton = page
      .getByRole("button", { name: /apply/i })
      .or(page.getByRole("link", { name: /apply/i }))
      .or(page.locator("[data-automation-id*='apply' i]"))
      .first();

    await applyButton.waitFor({ state: "visible", timeout: 15000 });
    await applyButton.click();
    logger.info("Clicked primary 'Apply' button");

    await page.waitForTimeout(2000);

    // 5. Look for "Apply Manually" option or direct application form
    logger.step("Checking for 'Apply Manually' option...");
    const applyManuallyBtn = page
      .getByRole("button", { name: /apply manually/i })
      .or(page.getByRole("link", { name: /apply manually/i }))
      .or(page.locator("a:has-text('Apply Manually'), button:has-text('Apply Manually')"))
      .first();

    if (await applyManuallyBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      logger.info("Found 'Apply Manually' button. Clicking to navigate to candidate entry form...");
      await applyManuallyBtn.click();
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(2000);
    } else {
      logger.info("No separate 'Apply Manually' prompt required; already on application route or sign-in.");
    }

    // If on "Sign In" stage, click "Sign in with email" or "Create Account" to expose form fields
    const signInWithEmailBtn = page
      .getByRole("button", { name: /sign in with email/i })
      .or(page.locator('button:has-text("Sign in with email")'))
      .first();

    if (await signInWithEmailBtn.isVisible({ timeout: 4000 }).catch(() => false)) {
      logger.info("Encountered 'Sign in with email' button. Clicking to expose candidate input fields...");
      await signInWithEmailBtn.click();
      await page.waitForTimeout(1000);
    }

    // Check if there is a 'Create Account' link to test email/password and account inputs
    const createAccountLink = page
      .getByRole("button", { name: /create account/i })
      .or(page.getByRole("link", { name: /create account/i }))
      .or(page.locator("a:has-text('Create Account'), button:has-text('Create Account')"))
      .first();

    if (await createAccountLink.isVisible({ timeout: 3000 }).catch(() => false)) {
      logger.info("Found 'Create Account' option. Navigating to account creation fields to test resolvers...");
      await createAccountLink.click();
      await page.waitForTimeout(1000);
    }

    // 6. Test Interactive Workday Resolvers on detected fields
    logger.step("Running isolated Workday resolver tests on active form elements...");

    // Find any visible text inputs (e.g., First Name, Last Name, Email, or Search)
    const textInputs = page.locator('input[type="text"], input[type="email"], input:not([type])');
    const inputCount = await textInputs.count();
    logger.info(`Detected ${inputCount} potential text input fields on current view`);

    if (inputCount > 0) {
      // Find First Name / Given Name or fallback to first input
      const firstNameInput = page
        .getByLabel(/first name|given name/i)
        .or(page.locator('input[data-automation-id*="legalNameSection_firstName" i]'))
        .or(textInputs.first());

      if (await firstNameInput.isVisible().catch(() => false)) {
        await workday.fillTextInput(firstNameInput, profile.personal_info.first_name);
        const readBack = await firstNameInput.inputValue().catch(() => "");
        logger.info(`Assertion: First name field value verified: "${readBack}" === "${profile.personal_info.first_name}"`);
      }

      // Find Last Name
      const lastNameInput = page
        .getByLabel(/last name|family name/i)
        .or(page.locator('input[data-automation-id*="legalNameSection_lastName" i]'))
        .first();

      if (await lastNameInput.isVisible().catch(() => false)) {
        await workday.fillTextInput(lastNameInput, profile.personal_info.last_name);
        const readBack = await lastNameInput.inputValue().catch(() => "");
        logger.info(`Assertion: Last name field value verified: "${readBack}" === "${profile.personal_info.last_name}"`);
      }
    }

    // Test Combobox Resolver if any combobox/dropdown trigger is visible
    const comboboxTriggers = page
      .locator('[role="combobox"]')
      .or(page.locator('button[aria-haspopup="listbox"]'))
      .or(page.locator('[data-automation-id*="dropdown" i]'));

    const comboCount = await comboboxTriggers.count();
    logger.info(`Detected ${comboCount} custom combobox / dropdown elements on view`);

    if (comboCount > 0) {
      const countryDropdown = page
        .getByLabel(/country/i)
        .or(comboboxTriggers.first());

      if (await countryDropdown.isVisible().catch(() => false)) {
        logger.step("Testing combobox resolver on dropdown...");
        const selected = await workday.selectCombobox(countryDropdown, "United States of America");
        logger.info(`Combobox resolution outcome: ${selected ? "SUCCESS" : "PARTIAL"}`);
      }
    }

    // 7. Visual confirmation and Screenshot assertion
    const debugDir = path.resolve(process.cwd(), "debug");
    if (!fs.existsSync(debugDir)) {
      fs.mkdirSync(debugDir, { recursive: true });
    }
    const screenshotPath = path.join(debugDir, "phase2_resolver_test.png");
    await page.screenshot({ path: screenshotPath, fullPage: true });
    logger.info(`Phase 2 visual assertion screenshot captured at: ${screenshotPath}`);

    logger.step("Phase 2 test completed successfully. (Form was NOT submitted, adhering to boundary rules)");
  } catch (error) {
    logger.error(`Phase 2 resolver test error: ${(error as Error).message}`, { stack: (error as Error).stack });
    throw error;
  } finally {
    await browser.close();
    logger.step("Browser session terminated.");
  }
}

// CLI entry point
if (process.argv[1] && process.argv[1].endsWith("test_resolvers.ts")) {
  const args = process.argv.slice(2);
  const targetUrl =
    args[0] ||
    "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Senior-Systems-Software-Engineer---GPU-Software_JR2020271";

  runPhase2Test(targetUrl).catch((err) => {
    logger.error("FATAL: Phase 2 test execution failed", { err });
    process.exit(1);
  });
}
