import * as fs from "node:fs";
import * as path from "node:path";
import { chromium, type Page } from "playwright";
import { loadProfile } from "./config.js";
import { logger } from "./logger.js";

interface InteractiveElementSnapshot {
  tag: string;
  role: string | null;
  name: string | null;
  id: string | null;
  type: string | null;
  placeholder: string | null;
  required: boolean;
  disabled: boolean;
  text: string | null;
  ariaLabel: string | null;
  ariaRequired: string | null;
  ariaExpanded: string | null;
  ariaHasPopup: string | null;
  classes: string[];
}

interface FormSnapshot {
  url: string;
  title: string;
  timestamp: string;
  entryPointFound: boolean;
  interactiveElementsCount: number;
  interactiveElements: InteractiveElementSnapshot[];
  rawA11ySnapshot: unknown;
}

/**
 * Traverses interactive DOM elements to extract semantic and accessibility metadata.
 */
async function captureInteractiveElements(page: Page): Promise<InteractiveElementSnapshot[]> {
  logger.debug("Traversing DOM for interactive selectors...");
  const elements = await page.evaluate(() => {
    const interactiveSelectors = [
      "button",
      "a[href]",
      "input",
      "select",
      "textarea",
      "[role='button']",
      "[role='link']",
      "[role='combobox']",
      "[role='textbox']",
      "[role='checkbox']",
      "[role='radio']",
      "[tabindex='0']",
      "[data-automation-id]"
    ].join(", ");

    const nodes = Array.from(document.querySelectorAll(interactiveSelectors));

    return nodes.map((node) => {
      const el = node as HTMLElement;
      const inputEl = el as HTMLInputElement;

      return {
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute("role") || null,
        name: el.getAttribute("name") || null,
        id: el.id || null,
        type: inputEl.type || null,
        placeholder: inputEl.placeholder || null,
        required: inputEl.required || el.getAttribute("aria-required") === "true",
        disabled: (el as HTMLButtonElement).disabled || el.getAttribute("aria-disabled") === "true",
        text: (el.innerText || "").trim().slice(0, 150) || null,
        ariaLabel: el.getAttribute("aria-label") || null,
        ariaRequired: el.getAttribute("aria-required") || null,
        ariaExpanded: el.getAttribute("aria-expanded") || null,
        ariaHasPopup: el.getAttribute("aria-haspopup") || null,
        classes: Array.from(el.classList),
      };
    });
  });

  logger.debug(`Found ${elements.length} raw interactive DOM elements`);
  return elements;
}

export async function runInspectionHarness(targetUrl: string): Promise<void> {
  logger.step("Starting Phase 1: Deterministic Data Layer & Inspection Harness", { targetUrl });

  // 1. Validate profile.json strictly
  logger.step("[1/5] Loading and validating profile.json against Zod schema...");
  const profile = loadProfile();
  logger.info(`Profile confirmed valid for candidate: ${profile.personal_info.full_name}`);

  // 2. Launch Chromium in non-headless mode with visible viewport
  logger.step("[2/5] Launching Chromium browser (non-headless)...");
  const browser = await chromium.launch({
    headless: false,
    slowMo: 100,
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
  });

  const page = await context.newPage();

  // Attach page-level diagnostic listeners for complete observability
  page.on("console", (msg) => {
    logger.debug(`Browser [${msg.type()}]: ${msg.text()}`);
  });

  page.on("pageerror", (err) => {
    logger.warn(`Browser unhandled page error: ${err.message}`);
  });

  page.on("response", (res) => {
    if (res.status() >= 400) {
      logger.debug(`Browser HTTP ${res.status()} response: ${res.url()}`);
    }
  });

  try {
    // 3. Navigate to target URL and wait for network idle
    logger.step(`[3/5] Navigating to URL: ${targetUrl}`);
    const navStartTime = Date.now();
    await page.goto(targetUrl, { waitUntil: "networkidle", timeout: 45000 });
    const navDuration = Date.now() - navStartTime;

    const pageTitle = await page.title();
    logger.info(`Navigation complete in ${navDuration}ms. Page title: "${pageTitle}"`);

    // 4. Locate main "Apply" entry point
    logger.step("[4/5] Inspecting page for 'Apply' entry point...");
    const applyButtonLocator = page
      .getByRole("button", { name: /apply/i })
      .or(page.getByRole("link", { name: /apply/i }))
      .or(page.locator("[data-automation-id*='apply' i]"));

    const count = await applyButtonLocator.count();
    const entryPointFound = count > 0;
    if (entryPointFound) {
      const applyText = await applyButtonLocator.first().innerText().catch(() => "");
      logger.info(`Located ${count} 'Apply' entry point element(s) on page`, { firstElementText: applyText });
    } else {
      logger.warn("No direct 'Apply' button/link matched using accessibility locators.");
    }

    // 5. Traverse accessibility tree and extract interactive snapshot
    logger.step("[5/5] Extracting accessibility tree and interactive elements snapshot...");
    let rawA11ySnapshot: unknown = null;
    try {
      const pageWithA11y = page as unknown as { accessibility?: { snapshot: (options?: unknown) => Promise<unknown> } };
      if (pageWithA11y.accessibility && typeof pageWithA11y.accessibility.snapshot === "function") {
        rawA11ySnapshot = await pageWithA11y.accessibility.snapshot({ interestingOnly: true });
        logger.debug("Captured Playwright accessibility tree snapshot");
      }
    } catch (e) {
      logger.warn(`Accessibility snapshot unavailable: ${(e as Error).message}`);
    }

    const interactiveElements = await captureInteractiveElements(page);
    logger.info(`Captured ${interactiveElements.length} interactive elements across DOM`);

    // Write to debug/form_snapshot.json
    const debugDir = path.resolve(process.cwd(), "debug");
    if (!fs.existsSync(debugDir)) {
      fs.mkdirSync(debugDir, { recursive: true });
    }

    const snapshotOutput: FormSnapshot = {
      url: targetUrl,
      title: pageTitle,
      timestamp: new Date().toISOString(),
      entryPointFound,
      interactiveElementsCount: interactiveElements.length,
      interactiveElements,
      rawA11ySnapshot,
    };

    const outputPath = path.join(debugDir, "form_snapshot.json");
    fs.writeFileSync(outputPath, JSON.stringify(snapshotOutput, null, 2), "utf-8");
    logger.info(`Form snapshot written to ${outputPath}`);
    logger.info(`Execution log saved to: ${logger.getLogFilePath()}`);
    logger.info(`Event stream JSONL saved to: ${logger.getTraceFilePath()}`);

  } catch (error) {
    logger.error(`Inspection harness failed with error: ${(error as Error).message}`, { stack: (error as Error).stack });
    throw error;
  } finally {
    await browser.close();
    logger.step("Browser session closed cleanly. Inspection harness complete.");
  }
}

// Command-line entry point
if (process.argv[1] && process.argv[1].endsWith("harness.ts")) {
  const args = process.argv.slice(2);
  const targetUrl = args[0] || "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Senior-Systems-Software-Engineer---GPU-Software_JR2020271";
  
  runInspectionHarness(targetUrl).catch((err) => {
    logger.error("FATAL: Phase 1 harness process exited with error", { err: (err as Error).message });
    process.exit(1);
  });
}
