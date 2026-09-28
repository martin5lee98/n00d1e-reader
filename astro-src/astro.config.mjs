// astro.config.mjs
//
// Per Astro's own current docs (docs.astro.build/en/guides/integrations-guide/cloudflare/)
// and Cloudflare's own Astro framework guide
// (developers.cloudflare.com/workers/frameworks/framework-guides/astro/):
// the adapter itself needs no special options for a standard on-demand-
// rendered site with D1 bindings -- bindings are configured in
// wrangler.jsonc, NOT here (that pattern was removed in adapter v10 per
// its CHANGELOG: "If you define your bindings in the astro.config.mjs
// file, you need to first migrate your project to use a wrangler.toml/
// wrangler.jsonc configuration file for defining your bindings").
//
// output: "server" (not "static") is required since every page here
// queries D1 at request time -- this is NOT a fully pre-rendered site.

import { defineConfig } from "astro/config";
import cloudflare from "@astrojs/cloudflare";
import { cacheCloudflare } from "@astrojs/cloudflare/cache";

export default defineConfig({
  output: "server",
  adapter: cloudflare({
    // platformProxy lets `astro dev` simulate the Cloudflare runtime
    // (including D1) locally, per Astro's docs -- without this,
    // Astro.locals.runtime.env.DB would be undefined in local dev.
    platformProxy: {
      enabled: true,
    },
  }),
  // Page caching (Astro 7 route caching + Cloudflare Workers Cache).
  // A cached response is served by Cloudflare WITHOUT running the Worker:
  // no D1 query, no CPU. Cache hits still count as Worker requests.
  // The adapter turns on Workers Cache in the deployed wrangler config
  // automatically when this provider is set. Caching is disabled in
  // `astro dev`, so verify on the live site (look for a HIT in the
  // response headers).
  cache: {
    provider: cacheCloudflare(),
  },
  routeRules: {
    // Articles only change every 6 hours (fetch.yml), so a 10-minute
    // cache costs nothing in freshness. swr: after 10 minutes, the old
    // copy is still served instantly while a fresh one is built in the
    // background. "N 小时前更新" labels can be up to ~10 minutes stale.
    "/": { maxAge: 600, swr: 3600, tags: ["pages"] },
    "/latest": { maxAge: 600, swr: 3600, tags: ["pages"] },
    "/category/[slug]": { maxAge: 600, swr: 3600, tags: ["pages"] },
    // A resized thumbnail for a given (width, source URL) never changes.
    "/img/[...params]": { maxAge: 2592000, tags: ["img"] },
    // ⚠️ The cache is keyed by URL path only, not cookies. Any future
    // page that differs for logged-in users (e.g. 端传媒 content) MUST
    // opt out with Astro.cache.set(false), or it could be cached and
    // served to the public.
  },
  vite: {
    build: {
      // Un-minified error output in wrangler's local preview, per
      // Astro's own troubleshooting docs -- makes early debugging of
      // the D1 wiring much easier; safe to remove once the site is
      // stable and you want smaller preview bundles.
      minify: false,
    },
  },
});
