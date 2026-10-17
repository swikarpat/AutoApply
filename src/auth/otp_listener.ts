import { ImapFlow } from "imapflow";
import { loadProfile } from "../config.js";
import { logger } from "../logger.js";

export function extractWalmartOtp(rawSource: string): string | null {
  // Decode Quoted-Printable encoding
  const decoded = rawSource
    .replace(/=\r?\n/g, "")
    .replace(/=([0-9A-F]{2})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)));

  // Target 6-digit verification code in HTML body
  const targetedMatch =
    decoded.match(/valid for 5 minutes[\s\S]{1,250}?<b>(\d{6})<\/b>/i) ||
    decoded.match(/<b>(\d{6})<\/b>/i) ||
    decoded.match(/verification code[\s\S]{1,150}?<b>(\d{6})<\/b>/i);

  if (targetedMatch && targetedMatch[1]) {
    return targetedMatch[1];
  }

  // Fallback: isolate body from MIME headers to prevent matching SMTP/ARC header IDs
  const bodyOnly = decoded.split(/\r?\n\r?\n/).slice(1).join("\n");
  const match = bodyOnly.match(/\b\d{6}\b/);
  return match ? match[0] : null;
}

export async function getNextUid(): Promise<number> {
  const profile = loadProfile();
  const emailCfg = profile.email_service || {
    imap_host: "imap.gmail.com",
    imap_port: 993,
    user: profile.personal_info.email,
    app_password: profile.workday_account?.password || ""
  };

  const client = new ImapFlow({
    host: emailCfg.imap_host || "imap.gmail.com",
    port: emailCfg.imap_port || 993,
    secure: true,
    auth: { user: emailCfg.user, pass: emailCfg.app_password },
    logger: false
  });

  await client.connect();
  try {
    const status = await client.status("INBOX", { uidNext: true });
    const uidNext = status && typeof status === "object" && status.uidNext ? status.uidNext : 1;
    logger.info(`getNextUid: Current INBOX uidNext is: ${uidNext}`);
    return uidNext;
  } finally {
    await client.logout().catch(() => {});
  }
}

export async function fetchOtpSinceUid(
  minUid: number,
  maxWaitSeconds = 60,
  onPollTick?: (elapsed: number) => Promise<void>,
  minTimestamp: number = Date.now() - 30000
): Promise<string> {
  const profile = loadProfile();
  const emailCfg = profile.email_service || {
    imap_host: "imap.gmail.com",
    imap_port: 993,
    user: profile.personal_info.email,
    app_password: profile.workday_account?.password || ""
  };

  const client = new ImapFlow({
    host: emailCfg.imap_host || "imap.gmail.com",
    port: emailCfg.imap_port || 993,
    secure: true,
    auth: { user: emailCfg.user, pass: emailCfg.app_password },
    logger: false
  });

  await client.connect();
  const start = Date.now();
  const mailboxesToCheck = ["INBOX", "[Gmail]/Trash", "[Gmail]/All Mail"];

  try {
    logger.step(
      `fetchOtpSinceUid: Polling for Walmart OTP (UID >= ${minUid} or received after ${new Date(
        minTimestamp
      ).toLocaleTimeString()})...`
    );

    while (Date.now() - start < maxWaitSeconds * 1000) {
      for (const box of mailboxesToCheck) {
        try {
          const lock = await client.getMailboxLock(box);
          try {
            const status = await client.status(box, { messages: true, uidNext: true });
            const totalMessages = status && typeof status === "object" && status.messages ? status.messages : 0;

            if (totalMessages > 0) {
              const fromSeq = Math.max(1, totalMessages - 4);
              for await (const msg of client.fetch(`${fromSeq}:*`, { envelope: true, uid: true, source: true })) {
                const subject = msg.envelope?.subject || "";
                const from = msg.envelope?.from?.[0]?.address || "";
                const msgDate = msg.envelope?.date ? new Date(msg.envelope.date).getTime() : 0;

                const isWalmart =
                  from.toLowerCase().includes("walmart") ||
                  subject.toLowerCase().includes("otp") ||
                  subject.toLowerCase().includes("verification");

                if (isWalmart) {
                  const isRecent =
                    (box === "INBOX" && minUid > 0 && msg.uid >= minUid) ||
                    msgDate >= minTimestamp - 15000 ||
                    Date.now() - msgDate < 5 * 60 * 1000;

                  if (isRecent) {
                    const rawSource = msg.source ? msg.source.toString("utf-8") : "";
                    const code = extractWalmartOtp(rawSource);
                    if (code) {
                      const dateStr = msg.envelope?.date instanceof Date ? msg.envelope.date.toISOString() : String(msg.envelope?.date || "");
                      logger.step(
                        `fetchOtpSinceUid: Successfully intercepted fresh OTP [${code}] from mailbox "${box}" (UID: ${msg.uid}, Date: ${dateStr})!`
                      );
                      return code;
                    }
                  }
                }
              }
            }
          } finally {
            lock.release();
          }
        } catch (boxErr) {
          logger.debug(`fetchOtpSinceUid notice while scanning ${box}: ${(boxErr as Error).message}`);
        }
      }

      const elapsed = Math.round((Date.now() - start) / 1000);
      logger.info(`fetchOtpSinceUid [${elapsed}s]: Awaiting fresh email across INBOX / Trash / All Mail...`);

      if (onPollTick) {
        try {
          await onPollTick(elapsed);
        } catch (tickErr) {
          logger.debug(`onPollTick handler notice: ${(tickErr as Error).message}`);
        }
      }

      await new Promise((r) => setTimeout(r, 2500));
    }

    throw new Error(`Timed out waiting for fresh email (UID >= ${minUid}) after ${maxWaitSeconds}s`);
  } finally {
    await client.logout().catch(() => {});
  }
}

export async function fetchLatestOtp(senderKeyword = "walmart", maxWaitSeconds = 60): Promise<string> {
  const minUid = await getNextUid().catch(() => 1);
  return fetchOtpSinceUid(minUid, maxWaitSeconds);
}

export class OtpListener {
  async waitForOtp(
    senderDomain: string = "walmart.com",
    minUid: number = 1,
    timeoutMs: number = 60000
  ): Promise<string> {
    return fetchOtpSinceUid(minUid, Math.floor(timeoutMs / 1000));
  }
}
