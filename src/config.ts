import * as fs from "node:fs";
import * as path from "node:path";
import yaml from "js-yaml";
import { ProfileSchema, type Profile } from "./schema.js";
import { logger } from "./logger.js";

/**
 * Loads and strictly validates profile.json against the Zod schema.
 * Throws a formatted error if validation fails or file is missing.
 */
export function loadProfile(filePath: string = path.resolve(process.cwd(), "profile.json")): Profile {
  logger.info(`Checking profile configuration at: ${filePath}`);

  if (!fs.existsSync(filePath)) {
    const err = `Profile configuration file not found at: ${filePath}`;
    logger.error(err);
    throw new Error(err);
  }

  let rawContent: string;
  try {
    rawContent = fs.readFileSync(filePath, "utf-8");
    logger.debug(`Read profile configuration file (${rawContent.length} bytes)`);
  } catch (err) {
    const msg = `Failed to read profile file at ${filePath}: ${(err as Error).message}`;
    logger.error(msg);
    throw new Error(msg);
  }

  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(rawContent);
    logger.debug("Successfully parsed JSON syntax");
  } catch (err) {
    const msg = `JSON parsing error in ${filePath}: ${(err as Error).message}`;
    logger.error(msg);
    throw new Error(msg);
  }

  logger.info("Validating profile data against Zod schema...");
  const result = ProfileSchema.safeParse(parsedJson);
  if (!result.success) {
    const errorDetails = result.error.errors
      .map((e) => `  - [${e.path.join(".") || "root"}]: ${e.message}`)
      .join("\n");
    const errMsg = `Deterministic Profile Validation Failed for '${filePath}':\n${errorDetails}`;
    logger.error(errMsg, { errors: result.error.errors });
    throw new Error(errMsg);
  }

  logger.info(`Profile schema validation passed for candidate: ${result.data.personal_info.full_name}`, {
    email: result.data.personal_info.email,
    roles: result.data.job_preferences.roles,
    experienceCount: result.data.experience.length,
    educationCount: result.data.education.length,
  });

  return result.data;
}
