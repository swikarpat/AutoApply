import * as fs from "node:fs";
import * as path from "node:path";
import { logger } from "../logger.js";

export interface AppliedJobRecord {
  reqId: string;
  title: string;
  url: string;
  appliedAt: string;
}

export interface AppliedJobsData {
  [company: string]: AppliedJobRecord[];
}

export class AppliedJobsTracker {
  private filePath: string;
  private data: AppliedJobsData;

  constructor(filePath?: string) {
    this.filePath = filePath || path.resolve(process.cwd(), "data", "applied_jobs.json");
    this.data = this.load();
  }

  private load(): AppliedJobsData {
    try {
      if (fs.existsSync(this.filePath)) {
        const content = fs.readFileSync(this.filePath, "utf-8");
        return JSON.parse(content) as AppliedJobsData;
      }
    } catch (err) {
      logger.error(`Failed to read applied_jobs.json: ${(err as Error).message}`);
    }

    // Default pre-populated initial structure
    const initialData: AppliedJobsData = {
      nvidia: [
        {
          reqId: "JR2020271",
          title: "Senior Systems Software Engineer - GPU Software",
          url: "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Senior-Systems-Software-Engineer---GPU-Software_JR2020271",
          appliedAt: "2026-10-17T05:00:00.000Z",
        },
      ],
    };
    this.save(initialData);
    return initialData;
  }

  private save(data: AppliedJobsData): void {
    try {
      const dir = path.dirname(this.filePath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      fs.writeFileSync(this.filePath, JSON.stringify(data, null, 2), "utf-8");
    } catch (err) {
      logger.error(`Failed to save applied_jobs.json: ${(err as Error).message}`);
    }
  }

  isApplied(company: string, reqId: string): boolean {
    const key = company.toLowerCase();
    const records = this.data[key] || [];
    return records.some((r) => r.reqId.toLowerCase() === reqId.toLowerCase());
  }

  recordApplication(company: string, reqId: string, title: string, url: string): void {
    const key = company.toLowerCase();
    if (!this.data[key]) {
      this.data[key] = [];
    }
    const existingIndex = this.data[key].findIndex(
      (r) => r.reqId.toLowerCase() === reqId.toLowerCase()
    );
    const newRecord: AppliedJobRecord = {
      reqId,
      title,
      url,
      appliedAt: new Date().toISOString(),
    };
    if (existingIndex >= 0) {
      this.data[key][existingIndex] = newRecord;
    } else {
      this.data[key].push(newRecord);
    }
    this.save(this.data);
    logger.info(`Recorded application in tracker: [${company.toUpperCase()}] ${title} (${reqId})`);
  }

  recordStale(company: string, reqId: string, reason = "JOB_ERROR"): void {
    this.recordApplication(company, reqId, `[STALE] ${reason}`, "");
  }

  getAppliedList(company?: string): AppliedJobRecord[] {
    if (company) {
      return this.data[company.toLowerCase()] || [];
    }
    return Object.values(this.data).flat();
  }
}
