# 阅览室 (Yuelanshi) — Astro + Cloudflare Workers + D1

This is the scaffold for the site side of the project: Astro pages that
query D1 for articles the `fetch.py`/GitHub Actions pipeline has
scraped, rendered as the approved homepage/`/latest`/category layouts.

## What's here

```
astro.config.mjs       Astro config, Cloudflare adapter
wrangler.jsonc          Cloudflare Worker config: D1 binding, assets, etc
package.json
src/
  env.d.ts              Type declarations for the D1 binding (see note below)
  layouts/
    SiteLayout.astro     Shared chrome: topbar, logo, category nav
  components/
    ColumnBlock.astro    The outlet/column card -- ported from the
                          approved mockups, used on both / and /latest
    ArticleThumbnail.astro  Thumbnail component, calls the /img proxy
  lib/
    db.ts                 D1 query functions (homepage, /latest, category)
  pages/
    index.astro            Homepage -- blocks grouped by category
    latest.astro            /latest -- blocks ordered by recency
    category/[slug].astro    Flat paginated list per category
    img/[...params].ts        Cloudflare Image Resizing proxy route
public/
  .assetsignore            Required so Cloudflare doesn't serve
                            _worker.js/_routes.json as static assets
```

## What this does NOT include yet

- Real `node_modules` / a run of `npm install` -- this is source only,
  not a fully initialized project directory.
- A real D1 database. You need to create one and apply `schema.sql`
  (in the project's top-level directory, alongside this astro-src/
  folder) before any page will show real content.
- Verification against a real `astro build` / `wrangler dev` run. Every
  file here was checked with `tsc` (confirmed no real syntax errors,
  and for `src/env.d.ts` specifically, confirmed by compiling it
  TOGETHER with a real `cloudflare:workers` import against the actual
  installed `@cloudflare/workers-types` package source -- not just
  checked in isolation or trusted from documentation prose) and
  cross-referenced against Astro's and Cloudflare's own current
  documentation. But none of it has run inside a real Astro project
  with `npm install` actually completed, so treat first real setup as
  still needing a debugging pass -- particularly around exact
  dependency versions, which move quickly for this ecosystem.

- **Worth knowing**: this project went through two real corrections
  during development, both caught by checking primary sources (Astro's
  own upgrade guide, and directly reading `@cloudflare/workers-types`'
  installed source) rather than trusting an initial plausible-looking
  answer: (1) `wrangler.jsonc`'s `main` field, and (2) `src/env.d.ts`'s
  binding-typing approach, which went through TWO iterations --
  `Astro.locals.runtime` (the old, removed API) to a `declare module
  "cloudflare:workers"` attempt that looked reasonable but failed to
  actually compile, to the final, verified-working `declare namespace
  Cloudflare { interface Env {...} }` pattern. If something here still
  doesn't compile against a real project, checking the relevant
  package's own shipped `.d.ts` source directly (as was eventually done
  here) is more reliable than searching for documentation prose about it.

## Setup, step by step

1. **Move this into a real project directory** and initialize it:
   ```
   cd astro-src
   npm install
   ```

2. **Create the D1 database** (if you haven't already, per the earlier
   fetch.py/d1_client.py work):
   ```
   npx wrangler d1 create yuelanshi-articles
   ```
   Copy the `database_id` this prints into `wrangler.jsonc`'s
   `d1_databases[0].database_id` field, replacing the placeholder.

3. **Apply the schema**:
   ```
   npm run db:migrate:local    # for local dev
   npm run db:migrate:remote   # for the real deployed database
   ```

3b. **Seed the `columns` table** (from the repo root; fetch.py scrapes
   nothing until this runs). Needs CLOUDFLARE_ACCOUNT_ID, D1_DATABASE_ID,
   CLOUDFLARE_API_TOKEN in your environment:
   ```
   python seed_columns.py --dry-run
   python seed_columns.py
   ```

4. **Generate real binding types** (replaces the hand-written
   `src/env.d.ts` with the adapter's own generated version, which will
   be more accurate than what's checked in here):
   ```
   npm run types
   ```

5. `wrangler.jsonc`'s `main` field is set to
   `@astrojs/cloudflare/entrypoints/server`, confirmed against Astro's
   own official v13/Astro 6 upgrade guide (this project pins
   astro@^7.3.4 / adapter@^14.3.3, both past that threshold) -- an
   earlier draft of this file used the old, pre-v13 path
   (`dist/_worker.js/index.js`) before this was checked and corrected.

6. **Local dev**:
   ```
   npm run dev
   ```
   `platformProxy.enabled: true` in `astro.config.mjs` should make the
   D1 binding available locally -- if `Astro.locals.runtime.env.DB` is
   undefined during local dev, this is the first thing to check.

7. **Deploy**:
   ```
   npm run deploy
   ```

## Design note

`ColumnBlock.astro` and `SiteLayout.astro` are faithful ports of the
approved `homepage-mockup.html` / `latest-mockup.html` files (same CSS
values, same class names) -- not a redesign. `category/[slug].astro`'s
layout has no precedent in those mockups (only the block-grouped and
single-column-of-blocks layouts were designed) and reuses the existing
`.headline-list`-style visual language as a conservative default rather
than introducing new design decisions as part of this wiring work.

## Deployment

`.github/workflows/deploy.yml` builds and deploys this site to Cloudflare
Workers on every push to `main` that touches `astro-src/**`. It's a
SEPARATE workflow from the article fetcher's `.github/workflows/fetch.yml`
(at the top-level project root) -- one runs on a schedule and writes to
D1 via the REST API from a plain GitHub Actions runner (see
`d1_client.py`'s docstring for why it can't use the binding API); this
one builds the Worker that reads D1 via the binding API to serve pages.

Before this workflow can succeed:
1. `astro-src/package-lock.json` needs to exist and be committed -- it
   doesn't yet, since `npm install` has never actually been run against
   this project. Run it locally once and commit the result.
2. `wrangler.jsonc`'s `database_id` placeholder needs to be replaced
   with a real D1 database id (see step 2 in Setup above).
3. The repo needs `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`
   secrets set (Settings -> Secrets and variables -> Actions). `fetch.yml`
   additionally needs a `D1_DATABASE_ID` secret (same id as in wrangler.jsonc).

The workflow applies `schema.sql` via `wrangler d1 execute` before
every deploy, marked `continue-on-error` since those `CREATE TABLE`
statements aren't idempotent and will fail (harmlessly) on every run
after the first. This is a real gap, not an oversight -- see the
workflow file's own comments for what a schema CHANGE (not just the
first-ever apply) would require instead (Wrangler's real migrations
system, not this flat-file approach).

## Image handling

Thumbnails go through `/img/{width}/{encoded-source-url}`, which uses
Cloudflare's "Transform via Workers" Image Resizing feature (confirmed
via Cloudflare's own current docs to work on any Workers zone, no
Pro/Business plan required for this specific method -- see that file's
header comment for sourcing). Only source hosts in `ALLOWED_SOURCE_HOSTS`
(one per site scraper, ftchinese/sspai/etc) are proxied; anything else
403s. Add a new host there whenever a new site scraper is added with a
genuinely new image CDN.
