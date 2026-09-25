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
