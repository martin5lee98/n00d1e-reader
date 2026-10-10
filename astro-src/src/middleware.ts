// src/middleware.ts
//
// Region handling for the `r` URL parameter (see src/lib/region.ts).
//
// Rules:
//   1. URL already has r=cn or r=hk -> never redirect. The visitor (or a
//      link they followed) chose it; a mainland visitor who edits the URL
//      to r=hk sees the full site, by design.
//   2. No valid r, visitor's IP is in a country listed in
//      REGION_BY_COUNTRY -> 302 redirect to the same URL with r added.
//   3. No valid r, any other country -> full version, no redirect.
//
// Caching (important):
//   Cloudflare's Workers Cache sits IN FRONT of this Worker and is keyed
//   by path + query string only -- not by country. So:
//   - Pages WITH r are safe to keep in that front cache (astro.config.mjs
//     routeRules): everyone asking for that exact URL gets the same page.
//   - Pages WITHOUT r must never be stored there, or a cached copy would
//     be served to mainland visitors without this code running. They are
//     marked no-store for the front cache; to still avoid a database
//     query per visit, the rendered page is kept with the Cache API
//     inside the Worker (which only runs after the country check above).

import { defineMiddleware } from "astro:middleware";
import { env } from "cloudflare:workers";
import { REGION_BY_COUNTRY, VALID_REGIONS, type RegionParam } from "./lib/region";

const INNER_CACHE_SECONDS = 600;

const NO_FRONT_CACHE = {
  "Cache-Control": "private, no-cache",
  "Cloudflare-CDN-Cache-Control": "no-store",
};

export const onRequest = defineMiddleware(async (context, next) => {
  const { request, url, locals } = context;

  // Thumbnails and build assets are the same for every region.
  if (url.pathname.startsWith("/img/") || url.pathname.startsWith("/_")) {
    return next();
  }

  const r = url.searchParams.get("r");
  if (r && VALID_REGIONS.has(r)) {
    locals.regionParam = r as RegionParam;
    locals.hideCnRestricted = r === "cn";
    const response = await next();
    // Standard cache header for CloudFront (which sits in front of this
    // site and ignores Cloudflare's own Cloudflare-CDN-Cache-Control).
    // Pages with r= are the same for every visitor, so shared caches may
    // keep them for 10 minutes; browsers always re-check (max-age=0).
    if (response.status === 200 && !response.headers.has("Cache-Control")) {
      return withHeaders(response, { "Cache-Control": "public, max-age=0, s-maxage=600" });
    }
    return response;
  }

  locals.regionParam = null;
  locals.hideCnRestricted = false;

  if (request.method !== "GET" && request.method !== "HEAD") {
    return next();
  }

  // Visitor country. Behind CloudFront, the connection comes from a
  // CloudFront server, so Cloudflare's own lookup (request.cf.country)
  // would give CloudFront's location; CloudFront passes the real
  // visitor's country in CloudFront-Viewer-Country instead (forwarded by
  // the AllViewerExceptHostHeader origin request policy). This header
  // could be faked by someone calling the origin directly, which only
  // lets them pick a version they could also pick with ?r=.
  // DEBUG_COUNTRY is only for testing with `wrangler dev --var`; it is
  // not set in production.
  const country: string | undefined =
    (env as { DEBUG_COUNTRY?: string }).DEBUG_COUNTRY ??
    request.headers.get("CloudFront-Viewer-Country") ??
    (request as Request & { cf?: { country?: string } }).cf?.country;

  const target = country ? REGION_BY_COUNTRY[country] : undefined;
  if (target) {
    const dest = new URL(url);
    dest.searchParams.set("r", target);
    return new Response(null, {
      status: 302,
      headers: { Location: dest.pathname + dest.search, ...NO_FRONT_CACHE },
    });
  }

  // Everyone else: full version at the plain URL, kept out of the front
  // cache but reused from the Worker's own cache.
  context.cache?.set(false);

  const innerCache = (caches as unknown as { default: Cache }).default;
  const cacheKey = new Request(url.toString(), { method: "GET" });

  const hit = await innerCache.match(cacheKey);
  if (hit) {
    return withHeaders(hit, NO_FRONT_CACHE);
  }

  const response = await next();
  if (request.method === "GET" && response.status === 200) {
    const toStore = withHeaders(response.clone(), {
      "Cache-Control": `public, s-maxage=${INNER_CACHE_SECONDS}`,
    });
    toStore.headers.delete("Cloudflare-CDN-Cache-Control");
    toStore.headers.delete("Set-Cookie");
    locals.cfContext?.waitUntil(innerCache.put(cacheKey, toStore));
  }
  return withHeaders(response, NO_FRONT_CACHE);
});

function withHeaders(response: Response, headers: Record<string, string>): Response {
  const out = new Response(response.body, response);
  for (const [name, value] of Object.entries(headers)) {
    out.headers.set(name, value);
  }
  return out;
}
