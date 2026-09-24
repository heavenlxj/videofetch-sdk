import { describe, expect, it, vi } from "vitest";
import { VideoFetch } from "../src";

/**
 * `destination` must be forwarded verbatim.
 *
 * The trap this guards against is the SDK "helpfully" filling in a default `type` (or any
 * other field) for a saved connection: the API reads the provider from the connection, and a
 * fabricated value would either be ignored or, for an unknown enum member, rejected outright.
 * The wire body is the contract, so we assert on it.
 */

const JOB = {
  id: "dl_abc123",
  status: "queued",
  url: "https://www.youtube.com/watch?v=x",
  format: "1080p",
};

function makeFetch(handler: (url: string, init: RequestInit) => Promise<Response>) {
  return vi.fn(async (url: string | URL | Request, init?: RequestInit) =>
    handler(String(url), init ?? {})) as unknown as typeof fetch;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Run one create() and return the JSON body that actually went out on the wire. */
async function captureBody(destination?: unknown): Promise<Record<string, unknown>> {
  let body: Record<string, unknown> = {};
  const fetchMock = makeFetch(async (_url, init) => {
    body = JSON.parse(String(init.body));
    return jsonResponse(202, JOB);
  });
  const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });

  await client.downloads.create({
    url: "https://www.youtube.com/watch?v=x",
    format: "1080p",
    ...(destination === undefined ? {} : { destination: destination as never }),
  });
  return body;
}

describe("destination on the wire", () => {
  it("sends a bare saved-connection id unchanged, adding nothing", async () => {
    const body = await captureBody({ id: "conn_9f1c2a34" });

    expect(body.destination).toEqual({ id: "conn_9f1c2a34" });
    expect(Object.keys(body.destination as object)).toEqual(["id"]);
  });

  it("still accepts the documented {type, id} spelling", async () => {
    const body = await captureBody({ type: "s3", id: "conn_9f1c2a34" });

    expect(body.destination).toEqual({ type: "s3", id: "conn_9f1c2a34" });
  });

  it("forwards inline credentials with their provider", async () => {
    const destination = {
      type: "s3",
      bucket: "my-bucket",
      region: "us-east-1",
      access_key_id: "AKIA...",
      secret_access_key: "s3cr3t",
      path: "videos/",
    };

    const body = await captureBody(destination);

    expect(body.destination).toEqual(destination);
  });

  it("omits destination entirely when it is not given", async () => {
    const body = await captureBody();

    expect(body).not.toHaveProperty("destination");
    expect(body).toMatchObject({ url: JOB.url, format: "1080p" });
  });
});
