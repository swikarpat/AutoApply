import { loadProfile } from "../config.js";
import { type Profile } from "../schema.js";
import { AppliedJobsTracker } from "./tracker.js";
import { logger } from "../logger.js";

export interface DiscoveredJob {
  company: string;
  title: string;
  reqId: string;
  location: string;
  url: string;
}

export class JobDiscoveryEngine {
  private profile: Profile;
  private tracker: AppliedJobsTracker;

  constructor(profile?: Profile, tracker?: AppliedJobsTracker) {
    this.profile = profile || loadProfile();
    this.tracker = tracker || new AppliedJobsTracker();
  }

  /**
   * Resolves company identifier and career site details from an identifier or URL.
   */
  private parseCompanyTarget(target: string): { company: string; type: "nvidia" | "workday" | "unknown"; url?: string; tenant?: string; site?: string } {
    const lower = target.toLowerCase();
    if (lower.includes("nvidia")) {
      return { company: "nvidia", type: "nvidia" };
    }

    const workdayMatch = target.match(/https?:\/\/([^.]+)\.(?:wd\d+\.)?myworkdayjobs\.com\/(?:[a-zA-Z-]+)\/([^/?#]+)/i);
    if (workdayMatch) {
      return {
        company: workdayMatch[1].toLowerCase(),
        type: "workday",
        url: target,
        tenant: workdayMatch[1],
        site: workdayMatch[2],
      };
    }

    return { company: target.toLowerCase(), type: "unknown" };
  }

  /**
   * Evaluates if a job location string meets candidate preferences:
   * Keeps "Remote" and target states like "CA" / "California", or items in profile.preferred_locations.
   */
  private matchesLocation(locationStr: string): boolean {
    if (!locationStr) return false;
    const loc = locationStr.toLowerCase();

    // 1. Always keep Remote roles
    if (loc.includes("remote")) {
      return true;
    }

    // 2. Keep target state CA / California
    if (/\bca\b/i.test(locationStr) || loc.includes("california") || loc.includes("santa clara") || loc.includes("san francisco")) {
      return true;
    }

    // 3. Match against profile.job_preferences.preferred_locations
    const preferred = this.profile.job_preferences.preferred_locations || [];
    for (const pref of preferred) {
      const prefLower = pref.toLowerCase().trim();
      if (prefLower === "remote" && loc.includes("remote")) return true;
      const tokens = prefLower.split(",").map((t) => t.trim());
      for (const token of tokens) {
        if (token && loc.includes(token)) return true;
      }
    }

    return false;
  }

  /**
   * Discovers candidate roles matching profile preferences for a given company or portal URL.
   */
  async discoverRoles(companyOrUrl: string): Promise<DiscoveredJob[]> {
    const target = this.parseCompanyTarget(companyOrUrl);
    const roles = this.profile.job_preferences.roles;

    logger.step(`JobDiscoveryEngine: Commencing role discovery for company: "${target.company}"`, {
      targetType: target.type,
      rolesCount: roles.length,
    });

    const discoveredQueue: DiscoveredJob[] = [];
    const seenReqIds = new Set<string>();

    for (const role of roles) {
      logger.info(`Searching open requisitions for target role: "${role}"...`);
      let foundJobs: DiscoveredJob[] = [];

      try {
        if (target.type === "nvidia") {
          foundJobs = await this.searchNvidiaPcsx(role);
        } else if (target.type === "workday" && target.tenant && target.site) {
          foundJobs = await this.searchWorkdayCxs(target.url!, target.tenant, target.site, role);
        } else {
          // Default to Nvidia PCSX if company is nvidia, else attempt generic Workday
          foundJobs = await this.searchNvidiaPcsx(role);
        }
      } catch (err) {
        logger.warn(`Search failed for role "${role}": ${(err as Error).message}`);
        continue;
      }

      for (const job of foundJobs) {
        const reqId = job.reqId.toUpperCase();

        // Filter 1: Deduplication in current run
        if (seenReqIds.has(reqId)) {
          continue;
        }

        // Filter 2: Check tracker (already applied)
        if (this.tracker.isApplied(target.company, reqId)) {
          logger.info(`Filtering out already-applied requisition [${target.company.toUpperCase()}]: ${reqId} ("${job.title}")`);
          continue;
        }

        // Filter 3: Location preference filter
        if (!this.matchesLocation(job.location)) {
          logger.debug(`Filtering out non-matching location: "${job.location}" for ${reqId} ("${job.title}")`);
          continue;
        }

        seenReqIds.add(reqId);
        discoveredQueue.push(job);
        logger.info(`Discovered eligible role: "${job.title}" (${reqId}) | Location: ${job.location}`);
      }
    }

    logger.step(`JobDiscoveryEngine: Discovery complete. Found ${discoveredQueue.length} fresh eligible requisitions.`);
    return discoveredQueue;
  }

  /**
   * Discovers the first eligible unapplied role.
   */
  async discoverFirstEligibleJob(companyOrUrl: string): Promise<DiscoveredJob | null> {
    const jobs = await this.discoverRoles(companyOrUrl);
    return jobs.length > 0 ? jobs[0] : null;
  }

  /**
   * Query Nvidia Eightfold / PCSX search API.
   */
  private async searchNvidiaPcsx(roleQuery: string): Promise<DiscoveredJob[]> {
    const endpoint = `https://jobs.nvidia.com/api/pcsx/search?domain=nvidia.com&query=${encodeURIComponent(roleQuery)}&location=&start=0`;
    const response = await fetch(endpoint, {
      headers: {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(`Nvidia PCSX search API returned status: ${response.status}`);
    }

    const data = (await response.json()) as {
      data?: {
        positions?: Array<{
          id: number;
          displayJobId?: string;
          atsJobId?: string;
          name: string;
          locations?: string[];
          location?: string;
          positionUrl?: string;
        }>;
      };
    };

    const positions = data.data?.positions || [];
    return positions.map((p) => {
      const reqId = (p.displayJobId || p.atsJobId || String(p.id)).trim();
      const loc = Array.isArray(p.locations) ? p.locations.join(", ") : p.location || "Remote";
      const jobUrl = `https://jobs.nvidia.com/careers/job/${p.id}`;
      return {
        company: "nvidia",
        title: p.name.trim(),
        reqId,
        location: loc,
        url: jobUrl,
      };
    });
  }

  /**
   * Query Workday standard CXS jobs API.
   */
  private async searchWorkdayCxs(portalUrl: string, tenant: string, site: string, roleQuery: string): Promise<DiscoveredJob[]> {
    const urlObj = new URL(portalUrl);
    const endpoint = `${urlObj.origin}/wday/cxs/${tenant}/${site}/jobs`;

    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      },
      body: JSON.stringify({
        appliedFacets: {},
        limit: 20,
        offset: 0,
        searchText: roleQuery,
      }),
    });

    if (!response.ok) {
      throw new Error(`Workday CXS search API returned status: ${response.status}`);
    }

    const data = (await response.json()) as {
      jobPostings?: Array<{
        title: string;
        externalPath: string;
        locationsText?: string;
        bulletFields?: string[];
      }>;
    };

    const postings = data.jobPostings || [];
    return postings.map((post) => {
      const match = post.externalPath.match(/_([A-Za-z0-9]+)$/);
      const reqId = match ? match[1] : post.externalPath;
      const jobUrl = `${urlObj.origin}${urlObj.pathname.replace(/\/job\/.*$/, "")}${post.externalPath}`;
      return {
        company: tenant.toLowerCase(),
        title: post.title.trim(),
        reqId,
        location: post.locationsText || "Remote",
        url: jobUrl,
      };
    });
  }
}

// Standalone CLI execution for testing discovery engine
if (process.argv[1] && process.argv[1].endsWith("job_discovery.ts")) {
  const target = process.argv[2] || "nvidia";
  const discovery = new JobDiscoveryEngine();

  discovery
    .discoverRoles(target)
    .then((jobs) => {
      if (jobs.length === 0) {
        logger.warn("No eligible unapplied requisitions found.");
        process.exit(1);
      }
      const primaryJob = jobs[0];
      logger.info(`[INFO] Discovered fresh role: "${primaryJob.title}" (${primaryJob.reqId}) -> ${primaryJob.url}`);
      console.log("\n=== DISCOVERED QUEUE ===");
      jobs.slice(0, 5).forEach((j, i) => {
        console.log(`${i + 1}. [${j.reqId}] ${j.title} (${j.location}) -> ${j.url}`);
      });
      process.exit(0);
    })
    .catch((err) => {
      logger.error(`Discovery CLI failed: ${(err as Error).message}`);
      process.exit(1);
    });
}
