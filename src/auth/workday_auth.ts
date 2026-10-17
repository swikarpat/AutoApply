import * as fs from "node:fs";
import * as path from "node:path";
import { type BrowserContext, type Page } from "playwright";
import { type Profile } from "../schema.js";
import { WorkdayResolver } from "../resolvers/workday_resolvers.js";
import { OtpListener, fetchLatestOtp, getNextUid, fetchOtpSinceUid } from "./otp_listener.js";
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
    sessionFilePathOrCompany?: string
  ) {
    this.page = page;
    this.context = context;
    this.profile = profile;
    this.resolver = new WorkdayResolver(page);

    if (sessionFilePathOrCompany && sessionFilePathOrCompany.endsWith(".json")) {
      this.sessionFilePath = sessionFilePathOrCompany;
    } else {
      const company = (sessionFilePathOrCompany || "nvidia").toLowerCase();
      this.sessionFilePath = path.resolve(process.cwd(), "data", "sessions", `workday_${company}.json`);
    }
  }

  hasSessionFile(): boolean {
    return fs.existsSync(this.sessionFilePath);
  }

  getSessionFilePath(): string {
    return this.sessionFilePath;
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

    // Credentials
    const credentials = this.profile.workday_account || {
      email: this.profile.personal_info.email,
      password: "ChangeMe2026!#",
    };

    // 1. Walmart Careers navigation & OTP Challenge Resolution
    if (targetJobUrl.includes("careers.walmart.com") || this.page.url().includes("careers.walmart.com")) {
      logger.info(`Navigating to Walmart landing URL: ${targetJobUrl}`);
      await this.page.goto(targetJobUrl, { waitUntil: "networkidle", timeout: 45000 });
      await this.page.waitForTimeout(2000);

      if (this.page.url().includes("/job-error")) {
        logger.warn(`Walmart requisition is no longer accessible (redirected to /job-error). Target: ${targetJobUrl}`);
        throw new Error(`REQUISITION_UNAVAILABLE: ${targetJobUrl}`);
      }

      // Dismiss cookie banner if visible
      const cookieBtn = this.page
        .locator('#onetrust-accept-btn-handler, button:has-text("Accept All"), button:has-text("Accept")')
        .first();
      if (await cookieBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        logger.info("Dismissing cookie banner...");
        await cookieBtn.click();
        await this.page.waitForTimeout(500);
      }

      // Locate visible Apply now button
      const applyBtn = this.page
        .locator('button[data-id="job-apply-button"]:visible, button:has-text("Apply now"):visible, a:has-text("Apply now"):visible')
        .first();

      if (await applyBtn.isVisible({ timeout: 10000 }).catch(() => false)) {
        logger.info("Clicking Walmart primary 'Apply now' button...");
        await applyBtn.click();
        await this.page.waitForLoadState("networkidle").catch(() => {});
        await this.page.waitForTimeout(2000);
      }

      if (this.page.url().includes("/job-error")) {
        logger.warn(`Walmart requisition is no longer accessible (redirected to /job-error). Target: ${targetJobUrl}`);
        throw new Error(`REQUISITION_UNAVAILABLE: ${targetJobUrl}`);
      }

      // Check if session or direct navigation already reached apply form
      const isAlreadyOnApplyForm =
        this.page.url().includes("/jobs/apply") ||
        (await this.page
          .locator('form, [data-testid*="apply" i], input[name*="name" i], button:has-text("Upload")')
          .first()
          .isVisible({ timeout: 4000 })
          .catch(() => false));

      if (isAlreadyOnApplyForm) {
        logger.info("[AUTH] Candidate already authenticated (session valid). Saving session state...");
        const sessionDir = path.resolve(process.cwd(), "data", "sessions");
        if (!fs.existsSync(sessionDir)) fs.mkdirSync(sessionDir, { recursive: true });
        await this.page.context().storageState({ path: path.join(sessionDir, "workday_walmart.json") }).catch(() => {});
        logger.step("[AUTH] Authentication handshake complete. Proceeding to Application Wizard Engine.");
        return;
      }

      // Handle contact-details / email entry
      if (this.page.url().includes("contact-details")) {
        logger.info("Walmart contact details page reached. Inspecting form state...");
        const emailInput = this.page.locator('input[type="text"]:visible, input[type="email"]:visible').last();
        const continueBtn = this.page.locator('button:has-text("Continue")').first();
        let minUid = 0;
        let minTimestamp = Date.now();

        if (await emailInput.isVisible({ timeout: 3000 }).catch(() => false)) {
          logger.info(`Submitting candidate email: ${this.profile.personal_info.email}`);
          await emailInput.fill(this.profile.personal_info.email);

          const termsCheckbox = this.page.locator('input[type="checkbox"]').first();
          if (await termsCheckbox.isVisible({ timeout: 2000 }).catch(() => false)) {
            await termsCheckbox.check();
          }

          // Record baseline min UID right before clicking continue:
          try {
            minUid = await getNextUid();
            logger.info(`Inbox baseline uidNext: ${minUid}`);
            minTimestamp = Date.now();
          } catch (e) {
            logger.warn(`Could not fetch baseline min UID: ${(e as Error).message}`);
          }

          if (await continueBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
            logger.info("Clicking 'Continue' on Walmart contact details...");
            await continueBtn.click();
            await this.page.waitForTimeout(3000);
          }
        }

        // If minUid was not recorded (e.g. view already opened), fetch it now
        if (minUid === 0) {
          try {
            minUid = await getNextUid();
            logger.info(`Inbox baseline uidNext: ${minUid}`);
            minTimestamp = Date.now();
          } catch {}
        }

        // Check for verification code challenge
        const searchInput = this.page.locator('header input, [role="search"] input').first();
        if (await searchInput.isVisible().catch(() => false)) {
          await searchInput.fill("").catch(() => {});
        }

        const otpInputs = this.page.locator(
          'div:has(> input[maxlength="1"]) input, [aria-label*="digit" i], [data-testid*="otp" i] input, input[inputmode="numeric"]'
        );
        const singleOtpInput = this.page
          .locator('input[data-automation-id="verificationCode"], input[name="code"], input[autocomplete="one-time-code"]')
          .first();

        const pageText = (await this.page.textContent("body").catch(() => "")) || "";
        const otpCount = await otpInputs.count().catch(() => 0);
        const isVerificationPage =
          otpCount > 0 ||
          (await singleOtpInput.isVisible({ timeout: 4000 }).catch(() => false)) ||
          /verification code|sent a verification code|enter the code/i.test(pageText);

        if (isVerificationPage) {
          logger.step(`Walmart verification page opened. Resolving fresh OTP with UID >= ${minUid}...`);
          let resent = false;
          const otpCode = await fetchOtpSinceUid(
            minUid,
            60,
            async (elapsed) => {
              if (elapsed >= 15 && !resent) {
                const resendBtn = this.page
                  .locator('button:has-text("Resend"), a:has-text("Resend"), [data-testid*="resend" i]')
                  .first();
                if (await resendBtn.isVisible().catch(() => false)) {
                  logger.step("15s elapsed without fresh OTP delivery. Clicking 'Resend code' to trigger dispatch...");
                  resent = true;
                  await resendBtn.click().catch(() => {});
                }
              }
            },
            minTimestamp
          );

          // Clear header search bar if populated
          if (await searchInput.isVisible().catch(() => false)) {
            await searchInput.fill("").catch(() => {});
          }

          // Fill the 6 boxes
          const digitBoxes = this.page.locator(
            'div:has(> input[maxlength="1"]) input, [aria-label*="digit" i], input[inputmode="numeric"]'
          );
          const digitCount = await digitBoxes.count().catch(() => 0);

          if (digitCount >= 6) {
            logger.info(`Populating 6 segmented OTP boxes with code: ${otpCode}`);
            for (let i = 0; i < 6; i++) {
              await digitBoxes.nth(i).click().catch(() => {});
              await digitBoxes.nth(i).fill(otpCode[i]).catch(() => {});
            }
            // Trigger native keyboard events across boxes
            await digitBoxes.first().click().catch(() => {});
            await this.page.keyboard.type(otpCode, { delay: 120 });
          } else if (otpCount > 0) {
            await otpInputs.first().click().catch(() => {});
            await this.page.keyboard.type(otpCode, { delay: 120 });
          } else if (await singleOtpInput.isVisible({ timeout: 2000 }).catch(() => false)) {
            await singleOtpInput.fill(otpCode);
          } else {
            await this.page.keyboard.type(otpCode, { delay: 120 });
          }

          await this.page.waitForTimeout(1000);

          const verifyBtn = this.page
            .locator('button[data-testid="otp-verify-button"], button[aria-label="Verify"]')
            .first();

          logger.info("Awaiting verify button to become visible and enabled...");
          await verifyBtn.waitFor({ state: "visible", timeout: 8000 }).catch(() => {});

          await this.page
            .waitForFunction(
              (btn) => btn && !btn.hasAttribute("disabled") && !btn.classList.contains("disabled"),
              await verifyBtn.elementHandle().catch(() => null),
              { timeout: 5000 }
            )
            .catch(() => {});

          logger.info("Clicking Verify button...");
          await verifyBtn.click();
          await this.page.waitForLoadState("networkidle").catch(() => {});

          // Safely check page switch
          const activePages = this.context.pages().filter((p) => !p.isClosed());
          if (activePages.length > 0 && (this.page.isClosed() || this.page !== activePages[activePages.length - 1])) {
            logger.info("Detected active tab transition after verification. Switching context...");
            this.page = activePages[activePages.length - 1];
            this.resolver = new WorkdayResolver(this.page);
            await this.page.waitForLoadState("domcontentloaded").catch(() => {});
          }

          // Await navigation away from contact-details or entrance into application wizard
          if (!this.page.isClosed()) {
            logger.info("Awaiting navigation away from contact-details or entrance into application wizard...");
            await Promise.race([
              this.page.waitForURL((url) => !url.href.includes("contact-details"), { timeout: 25000 }),
              this.page.waitForSelector('[data-automation-id="progressBar"], input[name="legalNameSection.firstName"]', { timeout: 25000 })
            ]).catch(() => {});
          }

          // If entrance into wizard is confirmed, save session and complete auth
          if (!this.page.isClosed() && (await this.isInsideWizard())) {
            logger.info("Confirmed entrance into application wizard! Saving session...");
            await this.saveSessionState();
            return;
          }
        }
      }
    } else if (targetJobUrl.includes("jobs.nvidia.com") || this.page.url().includes("jobs.nvidia.com")) {
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

    if (!this.page.isClosed()) {
      await this.page.waitForTimeout(2000);
    }

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

    // 4. Check if authenticated into apply form or inside wizard
    const isApplyForm =
      this.page.url().includes("/jobs/apply") ||
      (await this.page
        .locator('form, [data-testid*="apply" i], input[name*="name" i], button:has-text("Upload")')
        .first()
        .isVisible({ timeout: 4000 })
        .catch(() => false));

    if (isApplyForm || (await this.isInsideWizard())) {
      logger.info("[AUTH] Candidate successfully authenticated via OTP. Saving session state...");
      const sessionDir = path.resolve(process.cwd(), "data", "sessions");
      if (!fs.existsSync(sessionDir)) fs.mkdirSync(sessionDir, { recursive: true });
      await this.page.context().storageState({ path: path.join(sessionDir, "workday_walmart.json") }).catch(() => {});
      logger.step("[AUTH] Authentication handshake complete. Proceeding to Application Wizard Engine.");
      return;
    }


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
        const isApplyFormFallback =
          this.page.url().includes("/jobs/apply") ||
          (await this.page
            .locator('form, [data-testid*="apply" i], input[name*="name" i], button:has-text("Upload")')
            .first()
            .isVisible({ timeout: 4000 })
            .catch(() => false));

        if (isApplyFormFallback) {
          logger.info("[AUTH] Candidate successfully authenticated via OTP. Saving session state...");
          const sessionDir = path.resolve(process.cwd(), "data", "sessions");
          if (!fs.existsSync(sessionDir)) fs.mkdirSync(sessionDir, { recursive: true });
          await this.page.context().storageState({ path: path.join(sessionDir, "workday_walmart.json") }).catch(() => {});
          logger.step("[AUTH] Authentication handshake complete. Proceeding to Application Wizard Engine.");
          return;
        }

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
      .locator(
        'input[data-automation-id="legalNameSection_firstName"], [data-automation-id="addressSection_addressLine1"], [data-automation-id="progressBar"], h2:has-text("My Information"), h1:has-text("My Information")'
      )
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
