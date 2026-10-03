// src/lib/db.ts
//
// D1 query functions for the Astro site's read paths (homepage, /latest,
// category pages). Uses the Workers D1 BINDING API (env.DB.prepare...),
// NOT the REST API used by fetch.py -- these are genuinely different
// interfaces (see d1_client.py's docstring for why the fetcher needs
// REST instead: it runs outside the Workers runtime, on GitHub Actions,
// where no binding exists). The Astro site itself runs AS a Worker, so
// the binding API is the right, faster choice here.
//
// The two ranked-CTE queries below are exactly what was designed and
// sanity-checked against schema.sql's indexes earlier in this project
// (see that discussion for why idx_articles_column_sort is the one
// index that actually earns its place against these query shapes, and
// why COALESCE(published_at, fetched_at) in ORDER BY can't use a plain
// index -- SQLite falls back to an in-memory sort, which is fine at
// this project's current data volume but worth knowing isn't free).

export interface ArticleRow {
  id: number;
  column_id: number;
  url: string;
  title: string;
  description: string | null;
  image_url: string | null;
  author: string | null;
  published_at: string | null;
  fetched_at: string;
  extra: string | null; // JSON text, not parsed here -- callers parse if needed
  // joined from columns:
  site: string;
  column_key: string;
  outlet_name: string;
  column_name: string | null;
  category: string;
  source_url: string;
  rn: number; // rank within column, 1 = most recent
}

export interface ColumnBlock {
  column_id: number;
  column_key: string;
  outlet_name: string;
  column_name: string | null;
  category: string;
  source_url: string;
  articles: ArticleRow[];
  last_activity?: string; // only present for /latest's ordering
}

/**
 * Groups a flat list of ranked article rows (as returned by the two
 * queries below) into per-column blocks, preserving the row order
 * SQLite already gave us (category/column_id/rn, or last_activity/
 * column_id/rn) rather than re-sorting in JS -- the SQL's ORDER BY is
 * the source of truth for block and article ordering alike.
 */
function groupByColumn(rows: ArticleRow[]): ColumnBlock[] {
  const blocks = new Map<number, ColumnBlock>();
  const order: number[] = [];

  for (const row of rows) {
    if (!blocks.has(row.column_id)) {
      blocks.set(row.column_id, {
        column_id: row.column_id,
        column_key: row.column_key,
        outlet_name: row.outlet_name,
        column_name: row.column_name,
        category: row.category,
        source_url: row.source_url,
        articles: [],
      });
      order.push(row.column_id);
    }
    blocks.get(row.column_id)!.articles.push(row);
  }

  return order.map((id) => blocks.get(id)!);
}

/**
 * Runs a query that filters on columns.hide_in_cn, and if the database
 * doesn't have that column yet (code deployed before the ALTER TABLE was
 * run -- this took the whole site down once), runs it again without the
 * filter instead of failing. The fallback shows every column, so the
 * r=cn version is unfiltered until the database is updated; that is
 * logged so it shows up in `wrangler tail` / the Worker's logs.
 */
async function withFlagFallback<T>(run: (useFlag: boolean) => Promise<T>): Promise<T> {
  try {
    return await run(true);
  } catch (err) {
    if (String((err as Error)?.message ?? err).includes("hide_in_cn")) {
      console.error("columns.hide_in_cn is missing -- serving unfiltered. Run the ALTER TABLE in schema.sql's hide_in_cn note.");
      return run(false);
    }
    throw err;
  }
}

// `?N = ?N` keeps the bound parameter referenced when the filter is off.
function cnFilter(param: number, useFlag: boolean): string {
  return useFlag ? `AND (?${param} = 0 OR c.hide_in_cn = 0)` : `AND ?${param} = ?${param}`;
}

/**
 * Homepage query: top ARTICLES_PER_COLUMN articles for every active
 * column, ordered by category then column then recency-within-column.
 * A column with zero articles is absent from the result entirely (an
 * inner join through articles) -- this is the deliberate behavior
 * flagged when this query was first designed: a brand-new column with
 * no successful fetch yet simply doesn't render a block, rather than
 * showing an empty one.
 */
export async function getHomepageBlocks(
  db: D1Database,
  articlesPerColumn: number = 6,
  hideCnRestricted: boolean = false
): Promise<ColumnBlock[]> {
  const { results } = await withFlagFallback((useFlag) => db
    .prepare(
      `
      WITH ranked AS (
        SELECT
          a.id, a.column_id, a.url, a.title, a.description, a.image_url,
          a.author, a.published_at, a.fetched_at, a.extra,
          c.site, c.column_key, c.outlet_name, c.column_name, c.category, c.source_url,
          ROW_NUMBER() OVER (
            PARTITION BY a.column_id
            ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
          ) AS rn
        FROM articles a
        JOIN columns c ON c.id = a.column_id
        WHERE c.active = 1
          ${cnFilter(2, useFlag)}
      )
      SELECT * FROM ranked
      WHERE rn <= ?1
      ORDER BY category, column_id, rn
      `
    )
    .bind(articlesPerColumn, hideCnRestricted ? 1 : 0)
    .all<ArticleRow>());

  return groupByColumn(results);
}

/**
 * /latest query: same per-column ranking, but columns themselves are
 * ordered by MAX(fetched_at) descending -- i.e. whichever column has
 * the most recently FIRST-SEEN article (not necessarily the most
 * recently PUBLISHED one) sorts first. This matches the "N 小时前更新"
 * badge from the /latest mockup, and the design tradeoff already
 * flagged when this was designed: a stale block could in principle
 * outrank a technically-newer single article buried in a more active
 * block, since this ranks by column activity, not by flattening every
 * article into one global timeline.
 */
export async function getLatestBlocks(
  db: D1Database,
  articlesPerColumn: number = 6,
  hideCnRestricted: boolean = false
): Promise<ColumnBlock[]> {
  const { results } = await withFlagFallback((useFlag) => db
    .prepare(
      `
      WITH column_recency AS (
        SELECT column_id, MAX(fetched_at) AS last_activity
        FROM articles
        GROUP BY column_id
      ),
      ranked AS (
        SELECT
          a.id, a.column_id, a.url, a.title, a.description, a.image_url,
          a.author, a.published_at, a.fetched_at, a.extra,
          c.site, c.column_key, c.outlet_name, c.column_name, c.category, c.source_url,
          cr.last_activity,
          ROW_NUMBER() OVER (
            PARTITION BY a.column_id
            ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
          ) AS rn
        FROM articles a
        JOIN columns c ON c.id = a.column_id
        JOIN column_recency cr ON cr.column_id = a.column_id
        WHERE c.active = 1
          ${cnFilter(2, useFlag)}
      )
      SELECT * FROM ranked
      WHERE rn <= ?1
      ORDER BY last_activity DESC, column_id, rn
      `
    )
    .bind(articlesPerColumn, hideCnRestricted ? 1 : 0)
    .all<ArticleRow & { last_activity: string }>());

  const blocks = groupByColumn(results as ArticleRow[]);
  // Attach last_activity per block (same value across all rows of a
  // block, so the first row's value is representative) -- used by the
  // template to render the "N 小时前更新" badge.
  const activityByColumn = new Map<number, string>();
  for (const row of results as (ArticleRow & { last_activity: string })[]) {
    if (!activityByColumn.has(row.column_id)) {
      activityByColumn.set(row.column_id, row.last_activity);
    }
  }
  for (const block of blocks) {
    block.last_activity = activityByColumn.get(block.column_id);
  }
  return blocks;
}

/**
 * Category page query: flat, paginated list (not grouped into blocks)
 * for one category -- matches the shape sketched when this query was
 * first designed (WHERE c.category = ?1 AND c.active = 1, ORDER BY
 * COALESCE(published_at, fetched_at) DESC, LIMIT/OFFSET). Not yet
 * wired into a page in this pass -- provided here since it was already
 * designed and belongs in the same module as the other two queries,
 * but /category/[slug].astro itself is not part of this piece of work.
 */
export async function getCategoryArticles(
  db: D1Database,
  category: string,
  limit: number = 30,
  offset: number = 0,
  hideCnRestricted: boolean = false
): Promise<ArticleRow[]> {
  const { results } = await withFlagFallback((useFlag) => db
    .prepare(
      `
      SELECT a.id, a.column_id, a.url, a.title, a.description, a.image_url,
             a.author, a.published_at, a.fetched_at, a.extra,
             c.site, c.column_key, c.outlet_name, c.column_name, c.category, c.source_url,
             0 AS rn
      FROM articles a
      JOIN columns c ON c.id = a.column_id
      WHERE c.category = ?1 AND c.active = 1
        ${cnFilter(4, useFlag)}
      ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
      LIMIT ?2 OFFSET ?3
      `
    )
    .bind(category, limit, offset, hideCnRestricted ? 1 : 0)
    .all<ArticleRow>());

  return results;
}
