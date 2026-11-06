export interface Env {
  ORIGIN_URL?: string;
}

const DEFAULT_ORIGIN = "http://45.76.48.77.sslip.io";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const originBase = env.ORIGIN_URL || DEFAULT_ORIGIN;
    const targetUrl = new URL(url.pathname + url.search, originBase);

    const headers = new Headers(request.headers);
    headers.set("X-Forwarded-Host", url.hostname);
    headers.set("X-Forwarded-Proto", url.protocol.replace(":", ""));
    const clientIp = request.headers.get("CF-Connecting-IP");
    if (clientIp) {
      headers.set("X-Forwarded-For", clientIp);
      headers.set("X-Real-IP", clientIp);
    }

    const init: RequestInit = {
      method: request.method,
      headers: headers,
      redirect: "follow",
    };

    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
      (init as any).duplex = "half";
    }

    try {
      const originResponse = await fetch(targetUrl.toString(), init);
      const responseHeaders = new Headers(originResponse.headers);
      responseHeaders.set("X-Proxied-By", "Cloudflare-Edge-Domnir");

      return new Response(originResponse.body, {
        status: originResponse.status,
        statusText: originResponse.statusText,
        headers: responseHeaders,
      });
    } catch (err: any) {
      return new Response(
        JSON.stringify({
          error: "Origin Gateway Error",
          service: "domnir-edge-proxy",
          detail: "Failed to connect to Dómnir Vultr Cloud Compute origin at " + originBase,
          message: err?.message || String(err),
        }),
        {
          status: 502,
          headers: {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
          },
        }
      );
    }
  },
};
