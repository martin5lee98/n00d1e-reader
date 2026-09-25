// src/pages/img/[...params].ts
//
// Image resizing proxy, built on Cloudflare's "Transform via Workers"
// (fetch-subrequest) method -- confirmed via Cloudflare's own current
// docs (developers.cloudflare.com/images/optimization/transformations/
// transform-via-fetch/) to work on ANY zone hosting a Worker, no Pro/
// Business plan required for this specific method (some third-party
// summaries conflated this with the older /cdn-cgi/image/ URL-syntax
// method, which historically had different plan requirements -- these
// are two different features under the same product name, confirmed
// distinct in Cloudflare's docs).
//
// Pricing (per Cloudflare, checked 2026-09): first 5,000 unique
// transformations/month are free, then $0.50/1,000. A "unique
// transformation" is one (source URL + dimensions + format) combo --
// re-requesting the SAME resized image is served from cache, not
// re-billed. Worth monitoring usage once this is live; not expected to
// be a real cost at this project's scale, but not verified against
// actual traffic yet either.
//
// URL scheme: /img/{width}/{encoded-source-url}
//   e.g. /img/300/https%3A%2F%2Fupload.bbtnews.com.cn%2F...jpg
//
// Deliberately a PATH segment for width (not a query param) and the
// full source URL urlencoded as the final segment -- keeps this Worker
// route's own URLs cacheable by Cloudflare's edge cache under a stable
// key, and keeps the "hide the real image location" option open later
// if ever wanted (not used for that here, just noting the docs mention
// it as a benefit of the Workers method specifically).
//
// SECURITY: only allowlisted source domains are resized -- see
// ALLOWED_SOURCE_HOSTS below. This is NOT optional: without an
// allowlist, this route would function as an open image-resizing proxy
// for ANY url on the internet, which is both an abuse vector (someone
// could point arbitrary traffic through your Worker, consuming your
// transformation quota) and likely a violation of the spirit of "for
// your own site's images" that a free tier assumes. The allowlist is
// every source domain this project's scrapers actually pull images
// from -- see scrapers/sites/*.py for where each of these was
// confirmed.

import type { APIRoute } from "astro";

// Every image-source domain used by scrapers/sites/*.py, confirmed
// against each site module's build_image_url()/image field mapping.
// Add a new domain here whenever a new site scraper is added that
// returns a genuinely new image host -- this list is deliberately
// exhaustive and explicit rather than a wildcard/pattern match.
const ALLOWED_SOURCE_HOSTS = new Set([
  // thepaper.cn (scrapers/sites/thepaper.py: `pic` field)
  "imgpai.thepaper.cn",
  // yicai.com (scrapers/sites/yicai.py: `originPic` field)
  "imgcdn.yicai.com",
  // tencent_news.py: thumbnails_big/bigImage/thumbnails fields, used
  // directly as image_url with no URL construction (see that module's
  // _first_url()) -- so whatever host the real API returns is exactly
  // what reaches this allowlist. CONFIRMED by the user with a real
  // example: https://inews.gtimg.com/om_ls/O4_ZWO-.../0 (a .webp file).
  // Independently cross-checked against this project's own earlier
  // work: getUserHomepageInfo's `head_url` field (used while resolving
  // guest_suid for this same site) also returned a gtimg.com URL
  // (inews.gtimg.com/newsapp_ls/...), so this domain appearing for
  // article thumbnails too is consistent with tencent_news' general
  // CDN naming, not a one-off.
  "inews.gtimg.com",
  // ftchinese.com (scrapers/sites/ftchinese.py: build_image_url())
  "dq4atoxl7csa1.cloudfront.net",
  "images.ft.com", // fallback path, see ftchinese.py's build_fallback_image_url()
  // theinitium.com (scrapers/sites/initium.py: <media:content url>)
  "storage.ghost.io",
  // sspai.com (scrapers/sites/sspai.py: build_image_url())
  "rssfile.sspai.com",
  // bbtnews.com.cn (scrapers/sites/bbtnews.py: already-absolute <img src>)
  "upload.bbtnews.com.cn",
  // latepost.com (scrapers/sites/latepost.py: build_image_url())
  "www.latepost.com",
]);

const MAX_WIDTH = 2000; // sanity ceiling, prevents abuse via absurd width requests
const ALLOWED_WIDTHS = new Set([72, 150, 300, 700]); // see note below on why a fixed set

// A fixed, small set of allowed widths (rather than any arbitrary
// integer) is deliberate: each DISTINCT width is its own billable
// "unique transformation" under Cloudflare's pricing. An arbitrary
// open range (e.g. any width a buggy client happens to request) could
// multiply transformation count needlessly for images that are
// visually indistinguishable at nearby sizes. 72 = list-item thumbnail
// (matches the original homepage mockup's size), 150/300 = mid-size
// variants for larger cards, 700 = matches ftchinese.py's own fixed
// IMAGE_FIXED_SIZE, kept in sync intentionally so that site's already-
// sized images don't get re-transformed unnecessarily at a mismatched
// width.

export const GET: APIRoute = async ({ params, request }) => {
  const rawParams = params.params; // Astro's [...params] catch-all
  if (!rawParams) {
    return new Response("Missing image path", { status: 400 });
  }

  const segments = rawParams.split("/");
  const widthSegment = segments[0];
  const encodedSourceUrl = segments.slice(1).join("/");

  const width = Number.parseInt(widthSegment, 10);
  if (!Number.isFinite(width) || !ALLOWED_WIDTHS.has(width)) {
    return new Response(
      `Invalid width. Allowed: ${Array.from(ALLOWED_WIDTHS).join(", ")}`,
      { status: 400 }
    );
  }

  let sourceUrl: URL;
  try {
    sourceUrl = new URL(decodeURIComponent(encodedSourceUrl));
  } catch {
    return new Response("Invalid source URL", { status: 400 });
  }

  if (sourceUrl.protocol !== "https:") {
    // Refuse to proxy plain-http sources -- everything in
    // ALLOWED_SOURCE_HOSTS is expected to be https already (confirmed
    // per-site in each scraper module), so a request for an http URL
    // here is either a bug upstream or a manipulated request, not a
    // legitimate case to handle silently.
    return new Response("Only https source URLs are allowed", { status: 400 });
  }

  if (!ALLOWED_SOURCE_HOSTS.has(sourceUrl.hostname)) {
    return new Response(`Source host not allowlisted: ${sourceUrl.hostname}`, {
      status: 403,
    });
  }

  // The actual Cloudflare Image Resizing call -- a fetch() subrequest
  // with the cf.image options object, per Cloudflare's "Transform via
  // Workers" docs. fit: "scale-down" (not "cover" or "contain") means
  // the image is never upscaled past its original size -- matches the
  // behavior independently observed from images.ft.com's own resize
  // service earlier in this project (requesting a larger size than the
  // source has just returns the source's real size, not an upscaled
  // fake), so this mirrors that same non-destructive default.
  let resized: Response;
  try {
    resized = await fetch(sourceUrl.toString(), {
      cf: {
        image: {
          width,
          fit: "scale-down",
          format: "auto", // serves AVIF/WebP when the browser supports it, per Cloudflare's docs
          quality: 85,
        },
      },
    } as RequestInit & { cf: { image: Record<string, unknown> } });
  } catch (err) {
    return new Response("Upstream fetch failed", { status: 502 });
  }

  if (!resized.ok) {
    // Source image is missing/broken -- pass the failure through as a
    // 502 rather than pretending success. The display layer (see the
    // article-image component) is responsible for a visual fallback;
    // this route's job is just to report the real outcome honestly.
    return new Response(`Upstream returned ${resized.status}`, { status: 502 });
  }

  // Cache aggressively at Cloudflare's edge -- the resized output for a
  // given (source URL, width) pair never changes, so a long
  // s-maxage is safe. Browser-side caching is set shorter in case a
  // source URL is ever reused for genuinely different content (not
  // expected, given URLs are built from content-addressed filenames on
  // most of the source sites, but kept conservative rather than assumed).
  const headers = new Headers(resized.headers);
  headers.set("Cache-Control", "public, max-age=3600, s-maxage=2592000");

  return new Response(resized.body, {
    status: 200,
    headers,
  });
};
