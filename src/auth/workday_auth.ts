import * as fs from "node:fs";
import * as path from "node:path";
import { type BrowserContext, type Page } from "playwright";
import { type Profile } from "../schema.js";
import { WorkdayResolver } from "../resolvers/workday_resolvers.js";
import { logger } from "../logger.js";

export class WorkdayAuth {
  private page: Page;
  private context: BrowserContext;
  private profile: Profile;
  private resolver: WorkdayResolver;
  private sessionFilePath: string;

  constructor(
    page: Page,
    context: BrowserContext,
    profile: Profile,
    sessionFilePath?: string
  ) {
    this.page = page;
    this.context = context;
    this.profile = profile;
    this.resolver = new WorkdayResolver(page);
    this.sessionFilePath =
      sessionFilePath ||
      path.resolve(process.cwd(), "data", "sessions", "workday_nvidia.json");
  }

  hasSessionFile(): boolean {
    return fs.existsSync(this.sessionFilePath);
  }

  getSessionFilePath(): string {
    return this.sessionFilePath;
  }

  async authenticateOrResume(targetJobUrl: string): Promise<void> {
    const hasExistingSession = this.hasSessionFile();
    logger.step("WorkdayAuth: Initiating authentication / session check...", {
      targetJobUrl,
      hasSession: hasExistingSession,
    });

    // 1. Navigate to target URL
    const currentUrl = this.page.url();
    if (!currentUrl.includes("myworkdayjobs.com")) {
      logger.info(`Navigating to target job URL: ${targetJobUrl}`);
      await this.page.goto(targetJobUrl, { waitUntil: "networkidle", timeout: 45000 });
    }

    // 2. Click Primary "Apply" button
    const applyButton = this.page
      .getByRole("button", { name: /apply/i })
      .or(this.page.getByRole("link", { name: /apply/i }))
      .or(this.page.locator("[data-automation-id*='apply' i]"))
      .first();

    if (await applyButton.isVisible({ timeout: 10000 }).catch(() => false)) {
      logger.info("Clicking primary 'Apply' entry point...");
      await applyButton.click();
      await this.page.waitForTimeout(1500);
    }

    // 3. Click "Apply Manually" if prompted
    const applyManuallyBtn = this.page
      .getByRole("button", { name: /apply manually/i })
      .or(this.page.getByRole("link", { name: /apply manually/i }))
      .or(this.page.locator("a:has-text('Apply Manually'), button:has-text('Apply Manually')"))
      .first();

    if (await applyManuallyBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      logger.info("Found 'Apply Manually' button. Clicking to navigate to candidate entry form...");
      await applyManuallyBtn.click();
      await this.page.waitForLoadState("networkidle").catch(() => {});
      await this.page.waitForTimeout(2000);
    }

    // 4. Strict check: are we already inside the wizard?
    if (await this.isInsideWizard()) {
      logger.info("Confirmed inside Workday Application Wizard! Skipping auth.");
      await this.saveSessionState();
      return;
    }

    // Credentials
    const credentials = this.profile.workday_account || {
      email: this.profile.personal_info.email,
      password: "ChangeMe2026!#",
    };

    // 5. If "Sign in with email" button is visible, click it.
    const signInWithEmailBtn = this.page
      .getByRole("button", { name: /sign in with email/i })
      .or(this.page.locator('button:has-text("Sign in with email")'))
      .first();

    if (await signInWithEmailBtn.isVisible({ timeout: 8000 }).catch(() => false)) {
      logger.info("Clicking 'Sign in with email' button...");
      await signInWithEmailBtn.click();
      await this.page.waitForLoadState("networkidle").catch(() => {});
      await this.page.waitForTimeout(1000);
    }

    // Check the current view
    const currentViewUrl = this.page.url();
    const passwordInputVisible = await this.page.locator('input[type="password"]').first().isVisible({ timeout: 3000 }).catch(() => false);
    const verifyPasswordVisible = await this.page
      .locator('[data-automation-id="verifyPassword"], input[type="password"]:nth-of-type(2)')
      .first()
      .isVisible({ timeout: 1000 })
      .catch(() => false);

    const isLoginView = currentViewUrl.includes("/login") || (passwordInputVisible && !verifyPasswordVisible);

    const createAccountTrigger = this.page
      .getByRole("button", { name: /create account/i })
      .or(this.page.getByRole("tab", { name: /create account/i }))
      .or(this.page.locator('[data-automation-id="createAccountLink"]'))
      .or(this.page.getByRole("link", { name: /create account/i }))
      .or(this.page.locator("a:has-text('Create Account'), button:has-text('Create Account')"))
      .first();

    if (isLoginView) {
      logger.info("Active login view detected (URL contains /login or login form visible). Signing in directly...");
      await this.performSignIn(this.page, this.profile);
    } else if (await createAccountTrigger.isVisible({ timeout: 3000 }).catch(() => false)) {
      logger.info("Create Account trigger visible. Attempting account registration...");
      await createAccountTrigger.click();
      await this.page.waitForTimeout(1000);

      // Fill registration fields
      await this.performCreateAccountFields(credentials.email, credentials.password);

      // Click "Create Account" submit button
      const submitBtn = this.page
        .getByRole("button", { name: /create account/i })
        .or(this.page.locator('[data-automation-id="createAccountSubmitButton"]'))
        .or(this.page.locator('button[type="submit"]'))
        .first();

      logger.info("Clicking 'Create Account' submit button...");
      await submitBtn.click();
      await this.page.waitForTimeout(3000);

      // If URL changes to /login or a Sign In form appears, immediately call performSignIn
      const postSubmitUrl = this.page.url();
      const pageText = (await this.page.textContent("body").catch(() => "")) || "";
      const hasCollision =
        /already exists|already registered|already have an account/i.test(pageText) ||
        (await this.page.locator('[data-automation-id="errorWidget"]:has-text("account")').isVisible().catch(() => false));

      if (postSubmitUrl.includes("/login") || (await this.page.locator('button[data-automation-id="signInSubmitButton"], button[type="submit"]:has-text("Sign In")').isVisible().catch(() => false))) {
        logger.info("Redirected to Sign In page or Sign In form visible after registration. Signing in...");
        await this.performSignIn(this.page, this.profile);
      } else if (hasCollision) {
        logger.warn("Account already exists error banner displayed. Switching to Sign In tab...");
        const signInTab = this.page
          .getByRole("button", { name: /sign in/i })
          .or(this.page.getByRole("link", { name: /sign in/i }))
          .or(this.page.locator("a:has-text('Sign In'), button:has-text('Sign In')"))
          .first();

        if (await signInTab.isVisible().catch(() => false)) {
          await signInTab.click();
          await this.page.waitForTimeout(1000);
        }
        await this.performSignIn(this.page, this.profile);
      }
    } else {
      // Fallback: check if sign in submit is available or just try performSignIn
      logger.info("Defaulting to Sign In flow...");
      await this.performSignIn(this.page, this.profile);
    }

    // 3. Post-Auth Gate:
    // After performSignIn is submitted, wait for navigation into the wizard
    logger.step("Post-Auth Gate: Waiting for entrance into Step 1 form...");

    const step1Field = this.page
      .locator('input[data-automation-id="legalNameSection_firstName"], [data-automation-id="addressSection_addressLine1"]')
      .first();

    try {
      await step1Field.waitFor({ state: "visible", timeout: 30000 });
    } catch (e) {
      const debugDir = path.resolve(process.cwd(), "debug");
      if (!fs.existsSync(debugDir)) fs.mkdirSync(debugDir, { recursive: true });
      const postAuthScreen = path.join(debugDir, "post_auth_failure.png");
      await this.page.screenshot({ path: postAuthScreen, fullPage: true }).catch(() => {});
      logger.error(`Post-Auth Gate timed out waiting for Step 1 form. Current URL: ${this.page.url()}. Screenshot saved to: ${postAuthScreen}`);

      // Check if redirected to candidate userHome with a draft or apply continue button
      const continueDraftBtn = this.page.getByRole("button", { name: /continue application|start application|continue/i }).first();
      if (await continueDraftBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        logger.info("Detected 'Continue Application' on candidate home. Clicking to resume apply flow...");
        await continueDraftBtn.click();
        await step1Field.waitFor({ state: "visible", timeout: 15000 });
      } else {
        throw e;
      }
    }

    logger.info("Authentication verified. Landed inside Step 1 (My Information) form.");

    // Save authenticated session to data/sessions/workday_nvidia.json
    await this.saveSessionState();
  }

  /**
   * Fills the Create Account form inputs.
   */
  private async performCreateAccountFields(email: string, pass: string): Promise<void> {
    logger.step("WorkdayAuth: Filling registration fields...");

    // Password fields
    const passwordInput = this.page
      .getByLabel(/^password/i)
      .or(this.page.locator('input[type="password"]'))
      .first();

    const verifyPassInput = this.page
      .getByLabel(/verify new password|confirm password|verify password/i)
      .or(this.page.locator('[data-automation-id="verifyPassword"]'))
      .or(this.page.locator('input[type="password"]').nth(1));

    await passwordInput.waitFor({ state: "visible", timeout: 8000 }).catch(() => {});

    // Email
    const emailInput = this.page
      .getByLabel(/email address/i)
      .or(this.page.locator('input[type="email"]'))
      .or(this.page.locator('input[data-automation-id*="email" i]'))
      .first();

    if (await emailInput.isVisible().catch(() => false)) {
      logger.info(`Filling email: ${email}`);
      await this.resolver.fillTextInput(emailInput, email);
    }

    // Password & Verify Password
    if (await passwordInput.isVisible().catch(() => false)) {
      logger.info("Filling password...");
      await this.resolver.fillTextInput(passwordInput, pass);
    }

    if (await verifyPassInput.isVisible().catch(() => false)) {
      logger.info("Filling verify password...");
      await this.resolver.fillTextInput(verifyPassInput, pass);
    }

    // Consent Checkbox
    const consentCheckbox = this.page
      .getByRole("checkbox", { name: /i agree|terms/i })
      .or(this.page.locator('[data-automation-id="createAccountCheckbox"]'))
      .or(this.page.locator('input[type="checkbox"]'))
      .first();

    if (await consentCheckbox.isVisible().catch(() => false)) {
      logger.info("Checking consent checkbox...");
      await this.resolver.setCheckbox(consentCheckbox, true);
    }
  }

  /**
   * Dedicated helper performSignIn(page, profile):
   * - Wait for input[type="password"] to be visible (timeout: 5000ms).
   * - Locate email input: page.locator('input[type="email"], input[data-automation-id="email"], input[name="email"]').first().
   * - Clear and fill with profile.workday_account.email.
   * - Locate password input: page.locator('input[type="password"], input[data-automation-id="password"], input[name="password"]').first().
   * - Clear and fill with profile.workday_account.password.
   * - Locate and click the Sign In submit button: page.locator('button[data-automation-id="signInSubmitButton"], button[type="submit"]:has-text("Sign In")').first().click().
   * - Polls for error banner after clicking submit.
   */
  async performSignIn(page: Page, profile: Profile): Promise<void> {
    logger.step("WorkdayAuth: Performing Sign In...");

    const account = profile.workday_account || {
      email: profile.personal_info.email,
      password: "ChangeMe2026!#",
    };

    // Wait for input[type="password"] to be visible (timeout: 5000ms)
    const passwordInput = page
      .locator('input[type="password"], input[data-automation-id="password"], input[name="password"]')
      .first();
    await passwordInput.waitFor({ state: "visible", timeout: 5000 });

    // Locate email input: page.locator('input[type="email"], input[data-automation-id="email"], input[name="email"]').first()
    const emailInput = page
      .locator('input[type="email"], input[data-automation-id="email"], input[name="email"]')
      .first();

    // Clear and fill with profile.workday_account.email
    logger.info(`Filling Sign In email: ${account.email}`);
    await emailInput.fill(account.email);

    // Locate password input and clear/fill
    logger.info("Filling Sign In password...");
    await passwordInput.fill(account.password);

    // Locate and click the Sign In submit button
    // Note: Workday often places a transparent overlay `<div data-automation-id="click_filter" aria-label="Submit" role="button">` over `<button data-automation-id="signInSubmitButton">`
    const clickFilter = page.locator('div[data-automation-id="click_filter"]').first();
    const signInSubmit = page
      .locator('button[data-automation-id="signInSubmitButton"], button[type="submit"]:has-text("Sign In")')
      .first();

    logger.info("Clicking Sign In submit button...");
    if (await clickFilter.isVisible({ timeout: 2000 }).catch(() => false)) {
      await clickFilter.click({ force: true });
    } else {
      await signInSubmit.click({ force: true });
    }

    // Explicit Error Banner Detection on Sign In:
    // Poll for up to 5 seconds for any authentication error alert
    const errorBanner = page.locator(
      '[data-automation-id="errorMessage"], div[role="alert"]:has-text("wrong email address or password"), div:has-text("account might be locked")'
    ).first();

    const start = Date.now();
    while (Date.now() - start < 5000) {
      if (await errorBanner.isVisible().catch(() => false)) {
        const errText = await errorBanner.innerText().catch(() => "");
        logger.error(`Workday rejected credentials: ${errText.trim()}`);
        const debugDir = path.resolve(process.cwd(), "debug");
        if (!fs.existsSync(debugDir)) fs.mkdirSync(debugDir, { recursive: true });
        const errScreenshot = path.join(debugDir, "login_credential_error.png");
        await page.screenshot({ path: errScreenshot, fullPage: true }).catch(() => {});
        throw new Error("Workday authentication rejected: Invalid credentials or account locked.");
      }
      await page.waitForTimeout(500);
    }
  }

  /**
   * Strictly defines whether we are inside the wizard using exclusive DOM elements.
   * Does NOT rely on URL alone or generic breadcrumb text.
   */
  async isInsideWizard(): Promise<boolean> {
    // An active login/registration view is present if ANY of these exist:
    const hasLoginView =
      (await this.page.getByRole("button", { name: /sign in with email/i }).isVisible().catch(() => false)) ||
      (await this.page.getByRole("button", { name: /create account/i }).isVisible().catch(() => false)) ||
      (await this.page.locator('input[type="password"]').isVisible().catch(() => false));

    if (hasLoginView) {
      return false;
    }

    // Inside wizard strictly by presence of wizard Step 1 form fields:
    const hasLegalNameSection = await this.page
      .locator('input[data-automation-id="legalNameSection_firstName"], [data-automation-id="addressSection_addressLine1"]')
      .first()
      .isVisible()
      .catch(() => false);

    return hasLegalNameSection;
  }

  private async waitForWizardArrival(timeoutMs: number = 30000): Promise<boolean> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (await this.isInsideWizard()) {
        logger.info("Confirmed entrance into Step 1 form!");
        return true;
      }
      await this.page.waitForTimeout(1000);
    }
    return false;
  }

  async saveSessionState(): Promise<void> {
    try {
      const dir = path.dirname(this.sessionFilePath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      await this.page.waitForLoadState("networkidle").catch(() => {});
      await this.context.storageState({ path: this.sessionFilePath });
      logger.info(`Saved authenticated browser session state to: ${this.sessionFilePath}`);
    } catch (err) {
      logger.warn(`Could not save storage state: ${(err as Error).message}`);
    }
  }
}
