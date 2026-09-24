/**
 * Compile-time contract for `destination`.
 *
 * These are not executed — `npm run typecheck:contract` type-checks this file and fails if
 * the shape of `DestinationSpec` drifts. `tests/**` is excluded from the main `tsconfig.json`,
 * so without this file a regression in the union would only be caught by whoever hit it.
 *
 * The rules being locked down:
 *   1. A saved connection is usable with **just an id**. The provider lives on the connection,
 *      so the SDK must not demand it — `{ id: "conn_..." }` has to compile.
 *   2. The inline-credentials form must keep demanding a **concrete** provider. `{ type: "url" }`
 *      is not a storage destination: the server would fall back to platform delivery and
 *      silently ignore the bucket, so that combination must not compile.
 *
 * Note: for object literals TypeScript reports excess/missing properties on the offending
 * line, so the negative cases below are deliberately written on a single line with the
 * `@ts-expect-error` comment immediately above.
 */
import type { DestinationSpec, DownloadCreateParams } from "../../src/types";

// ── legal shapes ───────────────────────────────────────────────────────────────────────────
const savedIdOnly: DestinationSpec = { id: "conn_9f1c2a34" };
const savedWithType: DestinationSpec = { id: "conn_9f1c2a34", type: "s3" };
const platform: DestinationSpec = { type: "url" };
const inline: DestinationSpec = {
  type: "s3",
  bucket: "my-bucket",
  region: "us-east-1",
  access_key_id: "AKIA...",
  secret_access_key: "...",
  path: "videos/",
};

// the same shape through the public create() parameter
const createParams: DownloadCreateParams = {
  url: "https://www.youtube.com/watch?v=x",
  format: "1080p",
  destination: { id: "conn_9f1c2a34" },
};

// ── shapes that must NOT compile ───────────────────────────────────────────────────────────

// @ts-expect-error inline credentials need a concrete provider, otherwise the server falls back to "url"
const inlineWithoutType: DestinationSpec = { bucket: "b", access_key_id: "k", secret_access_key: "s" };

// @ts-expect-error "url" is not a storage destination — a bucket here would be silently ignored
const inlineClaimingUrl: DestinationSpec = { type: "url", bucket: "b", access_key_id: "k", secret_access_key: "s" };

// @ts-expect-error a saved connection is identified by its id, not by its provider
const savedWithoutId: DestinationSpec = { type: "s3" };

export const contract: DestinationSpec[] = [
  savedIdOnly, savedWithType, platform, inline, createParams.destination as DestinationSpec,
  inlineWithoutType, inlineClaimingUrl, savedWithoutId,
];
