import * as fs from "node:fs";
import * as path from "node:path";
import { type Profile } from "../schema.js";
import { logger } from "../logger.js";

export interface QACacheEntry {
  questionPattern: string;
  normalizedQuestion: string;
  answer: string | boolean | number;
  category: "work_auth" | "sponsorship" | "relocation" | "clearance" | "notice_period" | "general";
  source: "profile" | "manual" | "inferred";
  updatedAt: string;
}

export interface QACacheFile {
  entries: QACacheEntry[];
}

export class QuestionCacheEngine {
  private cacheFilePath: string;
  private cache: QACacheFile;
  private profile: Profile;

  constructor(profile: Profile, cacheFilePath?: string) {
    this.profile = profile;
    this.cacheFilePath = cacheFilePath || path.resolve(process.cwd(), "data", "qa_cache.json");
    this.cache = this.loadCache();
    this.seedFromProfile();
  }

  private loadCache(): QACacheFile {
    if (fs.existsSync(this.cacheFilePath)) {
      try {
        const raw = fs.readFileSync(this.cacheFilePath, "utf-8");
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed.entries)) {
          logger.debug(`Loaded ${parsed.entries.length} QA cache entries from ${this.cacheFilePath}`);
          return parsed as QACacheFile;
        }
      } catch (err) {
        logger.warn(`Failed reading QA cache at ${this.cacheFilePath}, initializing fresh.`, { err });
      }
    }
    return { entries: [] };
  }

  private saveCache(): void {
    try {
      const dir = path.dirname(this.cacheFilePath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      fs.writeFileSync(this.cacheFilePath, JSON.stringify(this.cache, null, 2), "utf-8");
      logger.debug(`Saved ${this.cache.entries.length} QA entries to ${this.cacheFilePath}`);
    } catch (err) {
      logger.error(`Error saving QA cache to ${this.cacheFilePath}`, { err });
    }
  }

  /**
   * Normalizes strings by lowercasing, stripping punctuation, and compressing whitespace.
   */
  public normalize(text: string): string {
    return text
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  /**
   * Computes Levenshtein distance between two strings.
   */
  private levenshteinDistance(a: string, b: string): number {
    const matrix: number[][] = [];
    for (let i = 0; i <= b.length; i++) matrix[i] = [i];
    for (let j = 0; j <= a.length; j++) matrix[0][j] = j;

    for (let i = 1; i <= b.length; i++) {
      for (let j = 1; j <= a.length; j++) {
        if (b.charAt(i - 1) === a.charAt(j - 1)) {
          matrix[i][j] = matrix[i - 1][j - 1];
        } else {
          matrix[i][j] = Math.min(
            matrix[i - 1][j - 1] + 1, // substitution
            matrix[i][j - 1] + 1,     // insertion
            matrix[i - 1][j] + 1      // deletion
          );
        }
      }
    }
    return matrix[b.length][a.length];
  }

  /**
   * Similarity score between 0.0 and 1.0 based on Levenshtein distance.
   */
  public similarity(s1: string, s2: string): number {
    const longer = s1.length > s2.length ? s1 : s2;
    if (longer.length === 0) return 1.0;
    const distance = this.levenshteinDistance(s1, s2);
    return (longer.length - distance) / longer.length;
  }

  /**
   * Populates baseline deterministic answers from profile.json ground truth.
   */
  private seedFromProfile(): void {
    const p = this.profile;

    const baselineSeeds: Array<Omit<QACacheEntry, "updatedAt">> = [
      // US Work Authorization
      {
        questionPattern: "Are you legally authorized to work in the United States?",
        normalizedQuestion: this.normalize("Are you legally authorized to work in the United States?"),
        answer: p.work_authorization.authorized_us ? "Yes" : "No",
        category: "work_auth",
        source: "profile",
      },
      {
        questionPattern: "authorized to work in the US",
        normalizedQuestion: this.normalize("authorized to work in the US"),
        answer: p.work_authorization.authorized_us ? "Yes" : "No",
        category: "work_auth",
        source: "profile",
      },
      // Sponsorship
      {
        questionPattern: "Will you now or in the future require sponsorship for employment visa status?",
        normalizedQuestion: this.normalize("Will you now or in the future require sponsorship for employment visa status?"),
        answer: p.work_authorization.sponsorship_required ? "Yes" : "No",
        category: "sponsorship",
        source: "profile",
      },
      {
        questionPattern: "require immigration sponsorship or visa transfer",
        normalizedQuestion: this.normalize("require immigration sponsorship or visa transfer"),
        answer: p.work_authorization.sponsorship_required ? "Yes" : "No",
        category: "sponsorship",
        source: "profile",
      },
      // Security Clearance
      {
        questionPattern: "Do you possess an active security clearance?",
        normalizedQuestion: this.normalize("Do you possess an active security clearance?"),
        answer: p.work_authorization.clearance === "None" ? "No" : "Yes",
        category: "clearance",
        source: "profile",
      },
      // Relocation
      {
        questionPattern: "Are you willing to relocate for this position?",
        normalizedQuestion: this.normalize("Are you willing to relocate for this position?"),
        answer: "Yes",
        category: "relocation",
        source: "profile",
      },
      // Notice Period
      {
        questionPattern: "What is your current notice period?",
        normalizedQuestion: this.normalize("What is your current notice period?"),
        answer: "2 weeks",
        category: "notice_period",
        source: "profile",
      },
    ];

    let newSeedsCount = 0;
    for (const seed of baselineSeeds) {
      const exists = this.cache.entries.some(
        (e) => e.normalizedQuestion === seed.normalizedQuestion
      );
      if (!exists) {
        this.cache.entries.push({
          ...seed,
          updatedAt: new Date().toISOString(),
        });
        newSeedsCount++;
      }
    }

    if (newSeedsCount > 0) {
      this.saveCache();
      logger.info(`Seeded ${newSeedsCount} ground-truth QA entries from profile.json`);
    }
  }

  /**
   * Resolves a question using exact match, substring match, or fuzzy distance.
   */
  public resolveQuestion(questionText: string, threshold: number = 0.72): QACacheEntry | null {
    const normQ = this.normalize(questionText);

    // 1. Direct normalized equality
    for (const entry of this.cache.entries) {
      if (entry.normalizedQuestion === normQ) {
        logger.debug(`Exact QA match found: "${questionText}" -> "${entry.answer}"`);
        return entry;
      }
    }

    // 2. Keyword/Substring heuristics for critical categories
    if (normQ.includes("authorized to work") || (normQ.includes("legally") && normQ.includes("work"))) {
      const entry = this.cache.entries.find((e) => e.category === "work_auth");
      if (entry) return entry;
    }

    if (normQ.includes("sponsorship") || normQ.includes("require visa")) {
      const entry = this.cache.entries.find((e) => e.category === "sponsorship");
      if (entry) return entry;
    }

    if (normQ.includes("clearance")) {
      const entry = this.cache.entries.find((e) => e.category === "clearance");
      if (entry) return entry;
    }

    if (normQ.includes("relocate") || normQ.includes("relocation")) {
      const entry = this.cache.entries.find((e) => e.category === "relocation");
      if (entry) return entry;
    }

    if (normQ.includes("notice period") || normQ.includes("start date")) {
      const entry = this.cache.entries.find((e) => e.category === "notice_period");
      if (entry) return entry;
    }

    // 3. Normalized string distance matching
    let bestMatch: QACacheEntry | null = null;
    let highestSim = 0;

    for (const entry of this.cache.entries) {
      const sim = this.similarity(normQ, entry.normalizedQuestion);
      if (sim > highestSim) {
        highestSim = sim;
        bestMatch = entry;
      }
    }

    if (bestMatch && highestSim >= threshold) {
      logger.debug(
        `Fuzzy QA match found (${(highestSim * 100).toFixed(1)}%): "${questionText}" -> "${bestMatch.answer}"`
      );
      return bestMatch;
    }

    logger.warn(`No QA answer cached for question: "${questionText}"`);
    return null;
  }

  /**
   * Records or updates a question answer into the cache file.
   */
  public setAnswer(
    question: string,
    answer: string | boolean | number,
    category: QACacheEntry["category"] = "general",
    source: QACacheEntry["source"] = "manual"
  ): void {
    const norm = this.normalize(question);
    const existingIndex = this.cache.entries.findIndex((e) => e.normalizedQuestion === norm);

    const newEntry: QACacheEntry = {
      questionPattern: question,
      normalizedQuestion: norm,
      answer,
      category,
      source,
      updatedAt: new Date().toISOString(),
    };

    if (existingIndex >= 0) {
      this.cache.entries[existingIndex] = newEntry;
    } else {
      this.cache.entries.push(newEntry);
    }

    this.saveCache();
    logger.info(`Cached answer for question: "${question}" => "${answer}"`);
  }
}
