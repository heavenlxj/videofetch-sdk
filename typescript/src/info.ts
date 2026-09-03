/** POST /v1/info — free metadata lookup (does not consume quota). */

import { VideoFetch } from "./client";
import { VideoInfo } from "./types";

export class InfoResource {
  constructor(private client: VideoFetch) {}

  async lookup(url: string): Promise<VideoInfo> {
    return this.client.request<VideoInfo>("POST", "/v1/info", { json: { url } });
  }
}
