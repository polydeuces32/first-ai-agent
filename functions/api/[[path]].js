export async function onRequest(context) {
  const { request, env } = context;
  const apiOrigin = (env.EVIDENCEOS_API_ORIGIN || "").trim().replace(/\/+$/, "");

  if (!apiOrigin) {
    return new Response("EVIDENCEOS_API_ORIGIN is not configured", { status: 500 });
  }

  const incomingUrl = new URL(request.url);
  const upstreamPath = incomingUrl.pathname.replace(/^\/api/, "") || "/";
  const upstreamUrl = new URL(`${upstreamPath}${incomingUrl.search}`, apiOrigin);

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");

  const init = {
    method: request.method,
    headers,
    redirect: "manual",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body;
  }

  return fetch(upstreamUrl, init);
}
