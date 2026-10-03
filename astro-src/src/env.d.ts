// src/env.d.ts
//
// Type declarations for the Worker's env, matching the bindings
// declared in wrangler.jsonc.
//
// CORRECTED: an earlier version of this file used the
// Astro.locals.runtime / Runtime<Env> / App.Locals pattern, which was
// the @astrojs/cloudflare v12-and-earlier approach. That whole pattern
// was removed as of adapter v13 / Astro 6 (see the corrected
// src/pages/*.astro files for the sourcing on this) -- the modern
// replacement imports `env` directly from "cloudflare:workers" at each
// call site (no Astro.locals involved at all), so there's no more
// App.Locals interface to declare here. This file now only needs to
// tell TypeScript what shape that imported `env` has.
//
// Astro's own docs recommend running `wrangler types` after any
// wrangler.jsonc change to auto-generate this instead of hand-
// maintaining it -- this file is a hand-written starting point (since
// this project's actual wrangler.jsonc was authored here, not by
// running the CLI against a real Cloudflare account) and should be
// REPLACED by running:
//     npx wrangler types
// once this project is initialized against a real Cloudflare account.
// The shape below matches what that command should generate for the
// single D1 binding currently in wrangler.jsonc, but has NOT been
// confirmed against real `wrangler types` output (no real Cloudflare
// account/wrangler CLI run was available while building this) --
// treat this as a best-effort placeholder, not a verified-correct file.

/// <reference types="astro/client" />
/// <reference types="@cloudflare/workers-types" />

// CORRECTED again after checking @cloudflare/workers-types' own
// source directly (not just documentation): the earlier version of
// this file tried `declare module "cloudflare:workers" { interface
// Env {...} }`, which does NOT work -- verified by actually compiling
// it, which failed with "has no exported member named 'env'". The
// package's own source (node_modules/@cloudflare/workers-types/index.d.ts)
// shows why: "cloudflare:workers" is declared as `export =
// CloudflareWorkersModule` (a namespace, not a set of named exports),
// and that module's own `env` export is typed against a SEPARATE
// ambient `Cloudflare.Env` interface -- with this exact comment in the
// library's own source: "The specific project can extend Env by
// redeclaring it in project-specific files. Typescript will merge all
// declarations... You can use wrangler types to generate the Env type
// automatically." So the correct augmentation target is
// Cloudflare.Env, not a module-level redeclaration. Confirmed by
// actually recompiling with this change (see the commit/conversation
// this file came from) -- this version, unlike the first attempt, was
// checked against the real installed package source, not guessed from
// documentation prose alone.
declare namespace Cloudflare {
  interface Env {
    DB: D1Database;
  }
}

// Set by src/middleware.ts on every page request.
declare namespace App {
  interface Locals {
    // "cn" | "hk" when the URL carries a valid r parameter, else null.
    regionParam: "cn" | "hk" | null;
    // true for r=cn: leave out columns marked hide_in_cn.
    hideCnRestricted: boolean;
  }
}
