import { describe, expect, it } from "vitest";
import { computeSignature, constructEvent, SignatureVerificationError } from "../src";

const SECRET = "whsec_test_secret";
const EVENT = JSON.stringify({ event: "download.completed", id: "dl_abc", status: "completed" });

describe("webhook verification", () => {
  it("accepts a valid signature", async () => {
    const sig = await computeSignature(EVENT, SECRET);
    expect(sig.startsWith("sha256=")).toBe(true);
    const out = await constructEvent(EVENT, sig, SECRET);
    expect(out).toEqual(JSON.parse(EVENT));
  });

  it("rejects a tampered payload", async () => {
    const sig = await computeSignature(EVENT, SECRET);
    const tampered = EVENT.replace("dl_abc", "dl_evil");
    await expect(constructEvent(tampered, sig, SECRET)).rejects.toBeInstanceOf(SignatureVerificationError);
  });

  it("rejects wrong secret", async () => {
    const sig = await computeSignature(EVENT, "wrong_secret");
    await expect(constructEvent(EVENT, sig, SECRET)).rejects.toBeInstanceOf(SignatureVerificationError);
  });

  it("rejects missing/malformed headers", async () => {
    await expect(constructEvent(EVENT, null, SECRET)).rejects.toBeInstanceOf(SignatureVerificationError);
    await expect(constructEvent(EVENT, "nope", SECRET)).rejects.toBeInstanceOf(SignatureVerificationError);
  });

  it("rejects an already-parsed object with SignatureVerificationError (not a TypeError)", async () => {
    const sig = await computeSignature(EVENT, SECRET);
    const parsed = JSON.parse(EVENT);
    let caught: unknown;
    try {
      // @ts-expect-error — deliberately passing the wrong runtime type
      await constructEvent(parsed, sig, SECRET);
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(SignatureVerificationError);
    expect(caught).not.toBeInstanceOf(TypeError);
    expect((caught as Error).message).toMatch(/raw request body/i);
  });

  it("verifies quota.* / balance.low events too", async () => {
    const body = JSON.stringify({ event: "quota.exceeded", alert_kind: "usage_threshold", level: "exceeded", threshold_pct: 100 });
    const sig = await computeSignature(body, SECRET);
    const out = await constructEvent(body, sig, SECRET);
    expect(out.event).toBe("quota.exceeded");
  });
});
