import * as path from "node:path";
import * as fs from "node:fs";
import { launchBrowserSession } from "./browser/launcher.js";
import { loadProfile } from "./config.js";
import { WorkdayAuth } from "./auth/workday_auth.js";
import { WorkdayWizardEngine } from "./engine/wizard_engine.js";
import { logger } from "./logger.js";

export async function runPhase3Wizard(targetUrl: string): Promise<void> {
  logger.step("=== COMMENCING PHASE 3: CANDIDATE AUTH & 5-STEP WIZARD ENGINE ===", { targetUrl });

  // 1. Load validated candidate profile
  const profile = loadProfile();
  logger.info(`Loaded candidate profile for: ${profile.personal_info.full_name}`);

  // 2. Determine session state file path
  const sessionPath = path.resolve(process.cwd(), "data", "sessions", "workday_nvidia.json");
  const sessionExists = fs.existsSync(sessionPath);

  // 3. Launch browser session (restoring storageState if available)
  const { browser, context, page } = await launchBrowserSession(
    false,
    sessionExists ? sessionPath : undefined
  );

  try {
    // 4. Authenticate or resume existing session
    const authEngine = new WorkdayAuth(page, context, profile, sessionPath);
    await authEngine.authenticateOrResume(targetUrl);

    // 5. Execute 5-step application wizard engine
    const wizardEngine = new WorkdayWizardEngine(page, profile);
    await wizardEngine.runFullWizard("./resume.pdf");

    logger.step("Phase 3 complete! Application reached final Review screen without submitting.");
  } catch (err) {
    logger.error(`Phase 3 wizard execution error: ${(err as Error).message}`, {
      stack: (err as Error).stack,
    });
    throw err;
  } finally {
    await browser.close();
    logger.step("Browser session closed cleanly.");
  }
}

// CLI entry point
if (process.argv[1] && process.argv[1].endsWith("test_wizard.ts")) {
  const args = process.argv.slice(2);
  const targetUrl =
    args[0] ||
    "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Senior-Systems-Software-Engineer---GPU-Software_JR2020271";

  runPhase3Wizard(targetUrl).catch((err) => {
    logger.error("FATAL: Phase 3 wizard test failed", { err: (err as Error).message });
    process.exit(1);
  });
}
