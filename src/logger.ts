import * as fs from "node:fs";
import * as path from "node:path";

export type LogLevel = "DEBUG" | "INFO" | "WARN" | "ERROR" | "STEP";

class Logger {
  private logDir: string;
  private logFile: string;
  private traceFile: string;

  constructor() {
    this.logDir = path.resolve(process.cwd(), "debug", "logs");
    if (!fs.existsSync(this.logDir)) {
      fs.mkdirSync(this.logDir, { recursive: true });
    }
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    this.logFile = path.join(this.logDir, `bot-run-${timestamp}.log`);
    this.traceFile = path.join(this.logDir, `trace-events-${timestamp}.jsonl`);
  }

  private write(level: LogLevel, message: string, meta?: unknown) {
    const time = new Date().toISOString();
    const metaStr = meta ? ` | meta: ${JSON.stringify(meta)}` : "";
    const logLine = `[${time}] [${level.padEnd(5)}] ${message}${metaStr}`;

    // Console output with colors/styling
    switch (level) {
      case "ERROR":
        console.error(`\x1b[31m${logLine}\x1b[0m`);
        break;
      case "WARN":
        console.warn(`\x1b[33m${logLine}\x1b[0m`);
        break;
      case "STEP":
        console.log(`\x1b[36m${logLine}\x1b[0m`);
        break;
      case "DEBUG":
        console.log(`\x1b[90m${logLine}\x1b[0m`);
        break;
      default:
        console.log(`\x1b[32m${logLine}\x1b[0m`);
    }

    // Persist to human-readable log file
    fs.appendFileSync(this.logFile, logLine + "\n", "utf-8");

    // Persist structured event to JSONL trace file
    const jsonEvent = JSON.stringify({
      timestamp: time,
      level,
      message,
      ...(meta ? { meta } : {}),
    });
    fs.appendFileSync(this.traceFile, jsonEvent + "\n", "utf-8");
  }

  info(message: string, meta?: unknown) {
    this.write("INFO", message, meta);
  }

  step(message: string, meta?: unknown) {
    this.write("STEP", message, meta);
  }

  debug(message: string, meta?: unknown) {
    this.write("DEBUG", message, meta);
  }

  warn(message: string, meta?: unknown) {
    this.write("WARN", message, meta);
  }

  error(message: string, meta?: unknown) {
    this.write("ERROR", message, meta);
  }

  getLogFilePath(): string {
    return this.logFile;
  }

  getTraceFilePath(): string {
    return this.traceFile;
  }
}

export const logger = new Logger();
