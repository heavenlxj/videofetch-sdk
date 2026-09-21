/**
 * Live integration test (v0.2.0) — runs against a REAL backend.
 *
 * Usage:
 *   VIDEOFETCH_API_KEY=vf_live_sk_... VIDEOFETCH_BASE_URL=http://127.0.0.1:8301 \
 *     node tests/integration.live.mjs
 *
 * The key is read from the environment (or VIDEOFERCH_KEY_FILE / /tmp/vfkey.json)
 * and is NEVER written into the repository.
 *
 * Prereq: `npm run build` (this imports the built dist/).
 */
import { readFileSync } from "node:fs";
import {
  VideoFetch, RateLimitError, SignatureVerificationError,
  constructEvent, computeSignature, WEBHOOK_EVENTS,
} from "../dist/index.js";

const BASE = process.env.VIDEOFETCH_BASE_URL || "http://127.0.0.1:8301";
const PROBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";

function loadKey() {
  if (process.env.VIDEOFETCH_API_KEY) return process.env.VIDEOFETCH_API_KEY;
  const file = process.env.VIDEOFETCH_KEY_FILE || "/tmp/vfkey.json";
  try {
    return JSON.parse(readFileSync(file, "utf8")).api_key;
  } catch {
    return undefined;
  }
}

const pass = (m) => console.log(`  ok   ${m}`);
const info = (m) => console.log(`  ·    ${m}`);
let failures = 0;
function check(cond, label) {
  if (cond) pass(label);
  else { failures += 1; console.error(`  FAIL ${label}`); }
}

async function main() {
  const apiKey = loadKey();
  if (!apiKey) {
    console.error("No API key. Set VIDEOFETCH_API_KEY (or provide /tmp/vfkey.json).");
    process.exit(2);
  }
  console.log(`\n== TS SDK v0.2.0 live integration @ ${BASE} ==`);

  const client = new VideoFetch({ apiKey, baseUrl: BASE, timeoutMs: 15_000, maxRetries: 0 });

  // ── usage.get() ──────────────────────────────────────────────────────────
  const usage = await client.usage.get();
  info(`usage.get(): plan=${usage.plan} quota_gb=${usage.quota_gb} remaining_gb=${usage.remaining_gb} ` +
       `concurrency_limit=${usage.concurrency_limit} alert_level=${usage.alert_level}`);
  check(usage.quota_gb === 1.0, "usage.get() quota_gb === 1.0 (free tier)");
  check(usage.concurrency_limit === 5, "usage.get() concurrency_limit === 5");
  check(typeof usage.key_id === "string" && usage.key_id.length > 0, "usage.get() has key_id");
  check(typeof usage.month === "string" && /^\d{4}-\d{2}$/.test(usage.month), `usage.get() month=${usage.month}`);
  check(["ok", "warning", "critical", "exceeded"].includes(usage.alert_level), `usage.get() alert_level=${usage.alert_level}`);

  // ── usage.alerts() ───────────────────────────────────────────────────────
  const alerts = await client.usage.alerts();
  info(`usage.alerts(): thresholds=${JSON.stringify(alerts.thresholds)} topup=${JSON.stringify(alerts.topup_amounts)} ` +
       `level=${alerts.state.level} crossed=${JSON.stringify(alerts.state.crossed)}`);
  check(JSON.stringify(alerts.thresholds) === JSON.stringify([80, 95, 100]), "usage.alerts() thresholds === [80,95,100]");
  check(alerts.topup_amounts.length > 0, "usage.alerts() has topup_amounts");
  check(alerts.state.quota_gb === 1.0, "usage.alerts() state.quota_gb === 1.0");
  check(alerts.state.pct_used === 0.0, "usage.alerts() state.pct_used === 0.0 (fresh account)");
  check(Array.isArray(alerts.fired), "usage.alerts() fired is an array");

  // ── webhooks create / list / delete ─────────────────────────────────────
  const url = `https://example.com/videofetch-sdk-test/${Date.now()}`;
  const created = await client.webhooks.create(url, ["download.completed", "quota.exceeded"]);
  info(`webhooks.create(): id=${created.id} events=${JSON.stringify(created.events)} secret_len=${created.secret.length}`);
  check(typeof created.id === "string" && created.id.length > 0, "webhooks.create() returns an id");
  check(created.secret.startsWith("whsec_") && created.secret.length > 22, "webhooks.create() returns full plaintext secret");
  check(!created.secret.includes("*"), "webhooks.create() secret is NOT masked");
  check(created.events.length === 2 && created.events.includes("quota.exceeded"), "webhooks.create() honours the events filter");

  const listed = await client.webhooks.list();
  const found = listed.items.find((w) => w.id === created.id);
  check(!!found, "webhooks.list() contains the created endpoint");
  check(found && found.secret.includes("*") && found.secret !== created.secret, "webhooks.list() secret is masked");

  await client.webhooks.delete(created.id);
  const after = await client.webhooks.list();
  check(!after.items.some((w) => w.id === created.id), "webhooks.delete() removes the endpoint (204)");

  // ── offline signature round-trip ────────────────────────────────────────
  const raw = JSON.stringify({ event: "quota.exceeded", level: "exceeded", threshold_pct: 100 });
  const sig = await computeSignature(raw, created.secret);
  const evt = await constructEvent(raw, sig, created.secret);
  check(evt.event === "quota.exceeded", "constructEvent() verifies a real create() secret");
  await constructEvent(raw, sig, created.secret);
  try {
    await constructEvent(JSON.parse(raw), sig, created.secret);
    check(false, "constructEvent(parsedObject) should throw");
  } catch (e) {
    check(e instanceof SignatureVerificationError, "constructEvent(parsedObject) → SignatureVerificationError");
  }
  check(WEBHOOK_EVENTS.length === 7, "WEBHOOK_EVENTS has 7 events");

  // ── wait() with a small poll interval ────────────────────────────────────
  const job = await client.downloads.create({ url: PROBE_URL, format: "mp3" });
  info(`downloads.create(): id=${job.id} status=${job.status}`);
  check(!!job.id, "downloads.create() returns a queued job");
  let retrieveCalls = 0;
  const origRetrieve = client.downloads.retrieve.bind(client.downloads);
  client.downloads.retrieve = async (id) => { retrieveCalls += 1; return origRetrieve(id); };
  let waitOutcome;
  try {
    const done = await job.wait({ pollIntervalMs: 150, timeoutMs: 1500 });
    waitOutcome = `terminal:${done.status}`;
  } catch (e) {
    // No worker on the dev box → jobs stay queued → wait() times out cleanly.
    waitOutcome = e instanceof VideoFetchErrorLike ? `error:${e.code ?? e.name}` : `error:${e.name}`;
  }
  info(`wait(): outcome=${waitOutcome} retrieveCalls=${retrieveCalls}`);
  check(retrieveCalls >= 1, "wait() polled the API at least once with a small pollIntervalMs");
  check(/terminal:|error:job_timeout|error:VideoFetchError/.test(waitOutcome),
        `wait() resolved or timed out cleanly (${waitOutcome})`);

  // cleanup: cancel the still-queued job so the account stays tidy
  try { await client.downloads.cancel(job.id); info(`downloads.cancel(${job.id}) ok`); }
  catch (e) { info(`downloads.cancel skipped: ${e.name}`); }

  // ── error semantics sanity (RateLimitError shape) ────────────────────────
  const bogus = new VideoFetch({ apiKey: "vf_invalid_key_for_probe", baseUrl: BASE, maxRetries: 0 });
  try {
    await bogus.usage.get();
    check(false, "invalid key should 401");
  } catch (e) {
    check(e.statusCode === 401, `invalid key → HTTP ${e.statusCode} (AuthenticationError)`);
  }
  info(`RateLimitError is exported: ${typeof RateLimitError === "function"}`);

  // ── live 429: fill the account concurrency window, then expect a limit error ─
  const burst = [];
  try {
    for (let i = 0; i < usage.concurrency_limit; i++) {
      burst.push(await client.downloads.create({ url: PROBE_URL, format: "mp3" }));
    }
    info(`created ${burst.length}/${usage.concurrency_limit} in-flight jobs`);
    const err = await client.downloads.create({ url: PROBE_URL, format: "mp3" })
      .then(() => null).catch((e) => e);
    check(err instanceof RateLimitError, "6th concurrent create → RateLimitError (429)");
    if (err instanceof RateLimitError) {
      info(`429: code=${err.code} limit=${err.limit} active=${err.active} scope=${err.scope} retryAfter=${err.retryAfter}`);
      check(["concurrency_limit_exceeded", "queue_limit_exceeded", "platform_at_capacity"].includes(err.code),
            `429 code is a known limit code (${err.code})`);
      check(err.statusCode === 429, "429 statusCode preserved");
      check(typeof err.retryAfter === "number" && err.retryAfter > 0, `Retry-After parsed (${err.retryAfter}s)`);
    }
  } finally {
    for (const j of burst) {
      try { await client.downloads.cancel(j.id); } catch { /* best effort */ }
    }
    info(`cleaned up ${burst.length} burst jobs`);
  }

  console.log(failures === 0 ? `\n== ALL TS INTEGRATION CHECKS PASSED ==\n`
                             : `\n== ${failures} TS INTEGRATION CHECK(S) FAILED ==\n`);
  process.exit(failures === 0 ? 0 : 1);
}

// tiny duck-type helper so we don't import the class just for a name check
const VideoFetchErrorLike = { [Symbol.hasInstance]: (o) => !!o && typeof o === "object" && "code" in o };

main().catch((e) => {
  console.error("\nIntegration crashed:", e);
  process.exit(1);
});
