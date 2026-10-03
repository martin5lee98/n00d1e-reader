// src/lib/region.ts
//
// Region versions of the site, chosen by the `r` URL parameter:
//   ?r=cn  -- hides columns marked hide_in_cn (see scrapers/registry.py)
//   ?r=hk  -- full version
//   (none) -- full version; see src/middleware.ts for when a visitor is
//             redirected to one of the above based on their country.

export type RegionParam = "cn" | "hk";

export const VALID_REGIONS = new Set<string>(["cn", "hk"]);

// Visitor country (Cloudflare's two-letter code) -> region to redirect to
// when the URL has no valid `r` yet. Countries not listed are not
// redirected and see the full version.
export const REGION_BY_COUNTRY: Record<string, RegionParam> = {
  CN: "cn",
  HK: "hk",
};

/** Keeps the visitor's region on internal links: "/latest" -> "/latest?r=cn". */
export function withRegion(href: string, region: RegionParam | null | undefined): string {
  if (!region) return href;
  return href + (href.includes("?") ? "&" : "?") + "r=" + region;
}
