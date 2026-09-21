/**
 * Usage resource: account-level quota snapshot + alert state.
 *
 *   const usage = await client.usage.get();        // GET /v1/usage
 *   const alerts = await client.usage.alerts();    // GET /v1/usage/alerts
 *
 * `usage.get()` is the cheap polling endpoint: quota_gb, month-to-date usage,
 * remaining credit, current alert_level and the concurrency limit. `alerts()`
 * adds the crossed thresholds, fired alert history and top-up presets.
 */

import { VideoFetch } from "./client";
import { Usage, UsageAlerts } from "./types";

export class UsageResource {
  constructor(private client: VideoFetch) {}

  /** GET /v1/usage — plan, quota/usage, balance, concurrency and alert level. */
  async get(): Promise<Usage> {
    return this.client.request<Usage>("GET", "/v1/usage");
  }

  /** GET /v1/usage/alerts — live alert state + fired records + thresholds/presets. */
  async alerts(): Promise<UsageAlerts> {
    return this.client.request<UsageAlerts>("GET", "/v1/usage/alerts");
  }
}
