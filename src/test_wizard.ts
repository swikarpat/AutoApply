import * as path from "node:path";
import * as fs from "node:fs";
import { launchBrowserSession } from "./browser/launcher.js";
import { loadProfile } from "./config.js";
import { WorkdayAuth, AlreadyAppliedError } from "./auth/workday_auth.js";
import { WorkdayWizardEngine } from "./engine/wizard_engine.js";
import { JobDiscoveryEngine } from "./discovery/job_discovery.js";
import { AppliedJobsTracker } from "./discovery/tracker.js";
import { logger } from "./logger.js";

export async function runPhase3Wizard(
  targetUrl: string,
  jobMetadata?: { company: string; reqId: string; title: string; url: string }
): Promise<void> {
  logger.step("=== COMMENCING PHASE 3: CANDIDATE AUTH & 5-STEP WIZARD ENGINE ===", { targetUrl });

  // 1. Load validated candidate profile
  const profile = loadProfile();
  logger.info(`Loaded candidate profile for: ${profile.personal_info.full_name}`);

  // 2. Determine session state file path dynamically
  const companySlug = (jobMetadata?.company || (targetUrl.includes("walmart") ? "walmart" : "nvidia")).toLowerCase();
  const sessionPath = path.resolve(process.cwd(), "data", "sessions", `workday_${companySlug}.json`);
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

    // 5. Execute 5-step application wizard engine using the active page
    const activePage = authEngine.getPage();
    const wizardEngine = new WorkdayWizardEngine(activePage, profile);
    await wizardEngine.runFullWizard("./resume.pdf");

    logger.step("Phase 3 complete! Application reached final Review screen without submitting.");

    // 6. Record application in tracker upon reaching Review screen successfully
    if (jobMetadata) {
      const tracker = new AppliedJobsTracker();
      tracker.recordApplication(jobMetadata.company, jobMetadata.reqId, jobMetadata.title, jobMetadata.url);
    }
  } catch (err) {
    if (err instanceof AlreadyAppliedError || (err as Error).name === "AlreadyAppliedError") {
      throw err;
    }
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
  const target = process.argv[2] || "nvidia";

  (async () => {
    let targetJobUrl = target;
    let jobMetadata: { company: string; reqId: string; title: string; url: string } | undefined;

    const isHttpUrl = target.startsWith("http://") || target.startsWith("https://");

    if (!isHttpUrl) {
      const tracker = new AppliedJobsTracker();
      const discovery = new JobDiscoveryEngine(undefined, tracker);
      const jobs = await discovery.discoverRoles(target);

      if (jobs.length === 0) {
        logger.warn(`No unapplied, eligible requisitions found for: "${target}".`);
        process.exit(1);
      }

      for (const role of jobs) {
        logger.step(`Testing requisition: "${role.title}" (${role.reqId}) -> ${role.url}`);
        try {
          await runPhase3Wizard(role.url, {
            company: role.company,
            reqId: role.reqId,
            title: role.title,
            url: role.url,
          });
          logger.step(`Successfully processed requisition ${role.reqId}. Exiting.`);
          break;
        } catch (err: any) {
          if (err.message?.includes("REQUISITION_UNAVAILABLE") || err.message?.includes("job-error")) {
            logger.warn(`Skipping unavailable role ${role.reqId} and advancing to next in queue...`);
            tracker.recordApplication(role.company, role.reqId, `[UNAVAILABLE] ${role.title}`, role.url);
            continue;
          }
          throw err;
        }
      }
    } else {
      await runPhase3Wizard(targetJobUrl, jobMetadata);
    }
  })()
    .then(() => {
      process.exit(0);
    })
    .catch((err) => {
      if (err instanceof AlreadyAppliedError || (err as Error).name === "AlreadyAppliedError") {
        logger.step("Status: SKIPPED (Job already applied). Test completed cleanly.");
        process.exit(0);
      }
      logger.error("FATAL: Phase 3 wizard test failed", { err: (err as Error).message });
      process.exit(1);
    });
}


