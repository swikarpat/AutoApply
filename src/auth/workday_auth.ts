import * as fs from "node:fs";
import * as path from "node:path";
import { type BrowserContext, type Page } from "playwright";
import { type Profile } from "../schema.js";
import { WorkdayResolver } from "../resolvers/workday_resolvers.js";
import { logger } from "../logger.js";

export class AlreadyAppliedError extends Error {
  constructor(msg = "Requisition already applied by candidate.") {
    super(msg);
    this.name = "AlreadyAppliedError";
  }
}

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

  getPage(): Page {
    return this.page;
  }

  async authenticateOrResume(targetJobUrl: string): Promise<void> {
    const hasExistingSession = this.hasSessionFile();
    logger.step("WorkdayAuth: Initiating authentication / session check...", {
      targetJobUrl,
      hasSession: hasExistingSession,
    });

    // 1. Eightfold-to-Workday Transition or direct Workday navigation
    if (targetJobUrl.includes("jobs.nvidia.com") || this.page.url().includes("jobs.nvidia.com")) {
      logger.info(`Navigating to Eightfold landing URL: ${targetJobUrl}`);
      await this.page.goto(targetJobUrl, { waitUntil: "networkidle", timeout: 45000 });
      await this.page.waitForTimeout(2000);

      // Dismiss any cookie banner if visible
      const cookieBtn = this.page
        .locator('#onetrust-accept-btn-handler, button:has-text("Accept All"), button:has-text("Accept")')
        .first();
      if (await cookieBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        logger.info("Dismissing cookie banner...");
        await cookieBtn.click();
        await this.page.waitForTimeout(500);
      }

      // Locate and click the primary "Apply" button on the page
      const applyBtn = this.page
        .locator('button:has-text("Apply"), a:has-text("Apply"), [data-test-id="apply-button"]')
        .first();

      if (await applyBtn.isVisible({ timeout: 10000 }).catch(() => false)) {
        logger.info("Clicking Eightfold primary 'Apply' button...");
        const popupPromise = this.context.waitForEvent("page", { timeout: 15000 }).catch(() => null);
        await applyBtn.click();

        const popup = await popupPromise;
        if (popup) {
          logger.info("Detected new browser tab for Workday application. Switching active page...");
          this.page = popup;
          this.resolver = new WorkdayResolver(this.page);
          await this.page.waitForLoadState("domcontentloaded").catch(() => {});
        } else {
          logger.info("Awaiting in-page navigation to Workday portal...");
          await this.page.waitForURL((url) => url.hostname.includes("myworkdayjobs.com"), { timeout: 15000 }).catch(() => {});
        }
      } else {
        const debugDir = path.resolve(process.cwd(), "debug");
        if (!fs.existsSync(debugDir)) fs.mkdirSync(debugDir, { recursive: true });
        await this.page
          .screenshot({ path: path.join(debugDir, "job_page_missing_apply.png"), fullPage: true })
          .catch(() => {});
        throw new Error(`Job page did not present an 'Apply' button. URL: ${this.page.url()}`);
      }
    } else {
      const currentUrl = this.page.url();
      if (!currentUrl.includes("myworkdayjobs.com")) {
        logger.info(`Navigating to target job URL: ${targetJobUrl}`);
        await this.page.goto(targetJobUrl, { waitUntil: "networkidle", timeout: 45000 });
      } else if (currentUrl !== targetJobUrl && !currentUrl.includes("/apply/")) {
        logger.info(`Navigating directly to target job URL: ${targetJobUrl}`);
        await this.page.goto(targetJobUrl, { waitUntil: "networkidle", timeout: 45000 });
      }
    }

    await this.page.waitForTimeout(2000);

    // If target URL is a Workday search query (e.g. ?q=JR...), click the matching job listing
    if (this.page.url().includes("?q=") || targetJobUrl.includes("?q=")) {
      logger.info("Direct requisition search page detected. Waiting for matching job posting...");
      const jobLink = this.page
        .locator('a[data-automation-id="jobTitle"], a[href*="/job/"]')
        .first();

      if (await jobLink.isVisible({ timeout: 15000 }).catch(() => false)) {
        logger.info(`Clicking matching job listing: "${await jobLink.innerText().catch(() => "")}"...`);
        await jobLink.click();
        await this.page.waitForLoadState("networkidle").catch(() => {});
        await this.page.waitForTimeout(2000);
        logger.info(`Navigated to canonical job posting: ${this.page.url()}`);
      }
    }

    // Check if Workday redirected to maintenance outage page
    const postNavUrl = this.page.url();
    if (postNavUrl.includes("/outage") || postNavUrl.includes("careers.nvidia.com") || postNavUrl.includes("about-nvidia/careers")) {
      const debugDir = path.resolve(process.cwd(), "debug");
      if (!fs.existsSync(debugDir)) fs.mkdirSync(debugDir, { recursive: true });
      await this.page.screenshot({ path: path.join(debugDir, "workday_maintenance_outage.png"), fullPage: true }).catch(() => {});
      throw new Error(`Workday application portal redirected to maintenance outage page: ${this.page.url()}`);
    }

    // 2. Click Primary "Apply" button on Workday if present
    const applyButton = this.page
      .getByRole("button", { name: /^apply$/i })
      .or(this.page.getByRole("link", { name: /^apply$/i }))
      .or(this.page.locator("[data-automation-id*='apply' i]"))
      .first();

    if (await applyButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      logger.info("Clicking primary Workday 'Apply' entry point...");
      await applyButton.click();
      await this.page.waitForTimeout(2000);
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
      await this.page.waitForLoadState("networkidle").catch(() => { });
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
      await this.page.waitForLoadState("networkidle").catch(() => { });
      await this.page.waitForTimeout(1000);
    }

    // Check the current view
    // Wait briefly for auth modal or login view elements to mount
    await this.page
      .locator('input[type="password"], button:has-text("Create Account"), a:has-text("Create Account"), [data-automation-id="createAccountLink"]')
      .first()
      .waitFor({ state: "visible", timeout: 8000 })
      .catch(() => { });

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

    if (isLoginView || passwordInputVisible) {
      logger.info("Active login view detected (URL contains /login or password input visible). Signing in directly...");
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
      // Check if password input has appeared now
      const pwdVisibleNow = await this.page.locator('input[type="password"]').first().isVisible({ timeout: 2000 }).catch(() => false);
      if (pwdVisibleNow) {
        logger.info("Password input detected on page. Signing in...");
        await this.performSignIn(this.page, this.profile);
      } else {
        const debugDir = path.resolve(process.cwd(), "debug");
        if (!fs.existsSync(debugDir)) fs.mkdirSync(debugDir, { recursive: true });
        await this.page.screenshot({ path: path.join(debugDir, "auth_view_unrecognized.png"), fullPage: true }).catch(() => {});
        throw new Error(`Unrecognized authentication view at URL: ${this.page.url()}. Neither Sign In nor Create Account fields were accessible.`);
      }
    }

    // 2. Strictly Gate Wizard Entrance in authenticateOrResume:
    // After performSignIn finishes, explicitly wait for the first Step 1 input to be attached and visible before proceeding:
    logger.step("Post-Auth Gate: Strictly waiting for Step 1 first name input to mount or checking already-applied state...");
    const firstNameInput = this.page
      .locator('input[data-automation-id="legalNameSection_firstName"], input[name="legalNameSection_firstName"]')
      .first();

    const alreadyAppliedLocator = this.page
      .locator('[data-automation-id="alreadyAppliedMessage"], div:has-text("already applied for this job"), h2:has-text("already applied for this job")')
      .first();

    const startWait = Date.now();
    let isAlreadyApplied = false;

    while (Date.now() - startWait < 30000) {
      if (await alreadyAppliedLocator.isVisible().catch(() => false)) {
        isAlreadyApplied = true;
        break;
      }
      if (await firstNameInput.isVisible().catch(() => false)) {
        break;
      }
      await this.page.waitForTimeout(500);
    }

    if (isAlreadyApplied) {
      // Save authenticated session because authentication was successful
      await this.saveSessionState();
      logger.info(`Requisition already applied: ${targetJobUrl}. Skipping gracefully.`);
      throw new AlreadyAppliedError();
    }

    try {
      await firstNameInput.waitFor({ state: "visible", timeout: 2000 });
    } catch (e) {
      // Final check for already applied
      if (await alreadyAppliedLocator.isVisible().catch(() => false)) {
        await this.saveSessionState();
        logger.info(`Requisition already applied: ${targetJobUrl}. Skipping gracefully.`);
        throw new AlreadyAppliedError();
      }

      const debugDir = path.resolve(process.cwd(), "debug");
      if (!fs.existsSync(debugDir)) fs.mkdirSync(debugDir, { recursive: true });
      const postAuthScreen = path.join(debugDir, "post_auth_failure.png");
      await this.page.screenshot({ path: postAuthScreen, fullPage: true }).catch(() => { });
      logger.error(`Post-Auth Gate timed out waiting for Step 1 firstNameInput. Current URL: ${this.page.url()}. Screenshot saved to: ${postAuthScreen}`);
      throw e;
    }

    logger.info("Authentication verified. Landed inside Step 1 (My Information) form.");

    // Only call saveSessionState() AFTER firstNameInput is confirmed visible on the page.
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

    await passwordInput.waitFor({ state: "visible", timeout: 8000 }).catch(() => { });

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

    // 1. Await Navigation Inside performSignIn:
    // After clicking the Sign In submit button (or click_filter overlay), wait for either:
    // a) Navigation away from /login: page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 15000 })
    // b) Or an error banner to appear: page.locator('[data-automation-id="errorMessage"], div[role="alert"]').first().waitFor({ state: 'visible', timeout: 5000 })
    const errorBannerLocator = page.locator(
      '[data-automation-id="errorMessage"], div[role="alert"], [data-automation-id="alertWidget"]'
    ).first();

    const navPromise = page
      .waitForURL((url) => !url.pathname.includes("/login"), { timeout: 15000 })
      .then(() => "NAVIGATED" as const);

    const errorPromise = errorBannerLocator
      .waitFor({ state: "visible", timeout: 5000 })
      .then(() => "ERROR" as const)
      .catch(() => "NO_ERROR" as const);

    const outcome = await Promise.race([navPromise, errorPromise]);

    if (outcome === "ERROR" || (await errorBannerLocator.isVisible().catch(() => false))) {
      const errorText = (await errorBannerLocator.innerText().catch(() => "")) || "Invalid credentials or account locked.";
      logger.error(`Workday rejected credentials: ${errorText.trim()}`);
      const debugDir = path.resolve(process.cwd(), "debug");
      if (!fs.existsSync(debugDir)) fs.mkdirSync(debugDir, { recursive: true });
      const errScreenshot = path.join(debugDir, "login_credential_error.png");
      await page.screenshot({ path: errScreenshot, fullPage: true }).catch(() => { });
      throw new Error("Authentication rejected: " + errorText.trim());
    }

    if (outcome !== "NAVIGATED") {
      // Wait remaining time for navigation away from /login if error check concluded with NO_ERROR
      await navPromise.catch(() => { });
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
      await this.page.waitForLoadState("networkidle").catch(() => { });
      await this.context.storageState({ path: this.sessionFilePath });
      logger.info(`Saved authenticated browser session state to: ${this.sessionFilePath}`);
    } catch (err) {
      logger.warn(`Could not save storage state: ${(err as Error).message}`);
    }
  }
}
