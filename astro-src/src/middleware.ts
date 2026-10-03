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
    return next();
  }

  locals.regionParam = null;
  locals.hideCnRestricted = false;

  if (request.method !== "GET" && request.method !== "HEAD") {
    return next();
  }

  // DEBUG_COUNTRY is only for testing with `wrangler dev --var`; it is
  // not set in production.
  const country: string | undefined =
    (env as { DEBUG_COUNTRY?: string }).DEBUG_COUNTRY ??
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
