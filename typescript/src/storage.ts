/**
 * Storage connections: connect a bucket once, then pass its `st_…` id as `destination`.
 *
 *   const check = await client.storage.test({ provider: "s3", bucket, region, access_key_id, secret_access_key });
 *   const conn = await client.storage.create({ provider: "s3", bucket, region, access_key_id, secret_access_key });
 *   const job = await client.downloads.create({ url, destination: conn.id });
 *
 * Set `is_default: true` and jobs created without a destination go to that connection.
 */

import { VideoFetch } from "./client";
import {
  StorageConnection, StorageConnectionList, StorageCreateParams, StorageTestParams,
  StorageTestResult, StorageUpdateParams,
} from "./types";

const path = (id: string) => `/v1/storage/${encodeURIComponent(id)}`;

export class StorageResource {
  constructor(private client: VideoFetch) {}

  /** GET /v1/storage — saved connections, default first. */
  async list(): Promise<StorageConnection[]> {
    const data = await this.client.request<StorageConnectionList>("GET", "/v1/storage");
    return data.items ?? [];
  }

  /** GET /v1/storage/{id} */
  async retrieve(id: string): Promise<StorageConnection> {
    return this.client.request<StorageConnection>("GET", path(id));
  }

  /**
   * POST /v1/storage — save a connection. The config is validated (422 {@link StorageError})
   * but not probed; call {@link test} first to check reachability and write permission.
   */
  async create(params: StorageCreateParams): Promise<StorageConnection> {
    return this.client.request<StorageConnection>("POST", "/v1/storage", { json: params });
  }

  /** PUT /v1/storage/{id} */
  async update(id: string, params: StorageUpdateParams): Promise<StorageConnection> {
    return this.client.request<StorageConnection>("PUT", path(id), { json: params });
  }

  /**
   * DELETE /v1/storage/{id}. Throws {@link ConflictError} (`storage_in_use`) while
   * queued/processing jobs target it, unless `{ force: true }`.
   */
  async delete(id: string, opts: { force?: boolean } = {}): Promise<void> {
    await this.client.request("DELETE", path(id), { params: opts.force ? { force: "true" } : undefined });
  }

  /**
   * Probe a saved connection (`test("st_…")`) or unsaved credentials (`test({...})`): writes
   * and removes a small object. A failed probe resolves with `ok: false`, a `storage_*`
   * code and per-step results; only a malformed config throws.
   */
  async test(target: string | StorageTestParams): Promise<StorageTestResult> {
    if (typeof target === "string") {
      return this.client.request<StorageTestResult>("POST", `${path(target)}/test`);
    }
    return this.client.request<StorageTestResult>("POST", "/v1/storage/test", { json: target });
  }
}
