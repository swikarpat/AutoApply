import { chromium, type Browser, type BrowserContext, type Page } from "playwright";
import { logger } from "../logger.js";

export interface BrowserSession {
  browser: Browser;
  context: BrowserContext;
  page: Page;
}

export async function launchBrowserSession(
  headless: boolean = false,
  storageStatePath?: string
): Promise<BrowserSession> {
  logger.step(`Launching Chromium browser (headless: ${headless})...`);

  const browser = await chromium.launch({
    headless,
    slowMo: 60,
  });

  const contextOptions: {
    viewport: { width: number; height: number };
    userAgent: string;
    storageState?: string;
  } = {
    viewport: { width: 1280, height: 900 },
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
  };

  if (storageStatePath) {
    contextOptions.storageState = storageStatePath;
    logger.debug(`Applying stored browser session state from: ${storageStatePath}`);
  }

  const context = await browser.newContext(contextOptions);

  const page = await context.newPage();

  // Attach diagnostic event listeners for full observability
  page.on("console", (msg) => {
    logger.debug(`Browser [${msg.type()}]: ${msg.text()}`);
  });

  page.on("pageerror", (err) => {
    logger.warn(`Browser page error: ${err.message}`);
  });

  page.on("response", (res) => {
    if (res.status() >= 400) {
      logger.debug(`Browser HTTP ${res.status()} on ${res.url()}`);
    }
  });

  return { browser, context, page };
}
