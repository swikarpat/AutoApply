import * as fs from "node:fs";
import * as path from "node:path";

export type LogLevel = "DEBUG" | "INFO" | "WARN" | "ERROR" | "STEP";

function getLocalFileTimestamp(): string {
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  let hours = d.getHours();
  const minutes = String(d.getMinutes()).padStart(2, "0");
  const seconds = String(d.getSeconds()).padStart(2, "0");
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12 || 12;
  const hoursStr = String(hours).padStart(2, "0");
  return `${year}-${month}-${day}T${hoursStr}-${minutes}-${seconds}-${ampm}`;
}

function getLocalLogTime(): string {
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  let hours = d.getHours();
  const minutes = String(d.getMinutes()).padStart(2, "0");
  const seconds = String(d.getSeconds()).padStart(2, "0");
  const ampm = hours >= 12 ? "PM" : "AM";
  hours = hours % 12 || 12;
  const hoursStr = String(hours).padStart(2, "0");
  return `${year}-${month}-${day} ${hoursStr}:${minutes}:${seconds} ${ampm}`;
}

class Logger {
  private logDir: string;
  private logFile: string;
  private traceFile: string;

  constructor() {
    this.logDir = path.resolve(process.cwd(), "debug", "logs");
    if (!fs.existsSync(this.logDir)) {
      fs.mkdirSync(this.logDir, { recursive: true });
    }
    const timestamp = getLocalFileTimestamp();
    this.logFile = path.join(this.logDir, `bot-run-${timestamp}.log`);
    this.traceFile = path.join(this.logDir, `trace-events-${timestamp}.jsonl`);

    // Initialize files and automatically prune to keep only the latest 2 of each
    try {
      fs.writeFileSync(this.logFile, "", { flag: "a" });
      fs.writeFileSync(this.traceFile, "", { flag: "a" });
    } catch {}
    this.cleanupOldLogs(2);
  }

  public cleanupOldLogs(maxKeep = 2) {
    try {
      if (!fs.existsSync(this.logDir)) return;
      const entries = fs.readdirSync(this.logDir);

      const logFiles = entries
        .filter((file) => file.endsWith(".log"))
        .map((file) => ({
          name: file,
          fullPath: path.join(this.logDir, file),
          mtime: fs.statSync(path.join(this.logDir, file)).mtimeMs,
        }))
        .sort((a, b) => b.mtime - a.mtime || b.name.localeCompare(a.name));

      if (logFiles.length > maxKeep) {
        for (const file of logFiles.slice(maxKeep)) {
          try {
            fs.unlinkSync(file.fullPath);
          } catch {}
        }
      }

      const jsonlFiles = entries
        .filter((file) => file.endsWith(".jsonl"))
        .map((file) => ({
          name: file,
          fullPath: path.join(this.logDir, file),
          mtime: fs.statSync(path.join(this.logDir, file)).mtimeMs,
        }))
        .sort((a, b) => b.mtime - a.mtime || b.name.localeCompare(a.name));

      if (jsonlFiles.length > maxKeep) {
        for (const file of jsonlFiles.slice(maxKeep)) {
          try {
            fs.unlinkSync(file.fullPath);
          } catch {}
        }
      }
    } catch {}
  }

  private write(level: LogLevel, message: string, meta?: unknown) {
    const time = getLocalLogTime();
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
