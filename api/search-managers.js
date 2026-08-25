// Vercel serverless function: best-effort FPL manager name search.
//
// The official FPL API has no name-search endpoint at all. This proxies an
// UNDOCUMENTED third-party API (api.fplbot.app, reverse-engineered from
// fplbot.app/search's own frontend bundle) that maintains its own crowd-
// sourced index of managers it has seen. It is NOT official, NOT
// comprehensive, and can change or disappear without notice -- so this
// always degrades to an empty result set rather than erroring the page.
//
// GET /api/search-managers?q=some+name

export default async function handler(req, res) {
  const q = String(req.query.q || "").trim();

  if (q.length < 2) {
    return res.status(400).json({ error: "Type at least 2 characters to search.", hits: [] });
  }

  try {
    const url = `https://api.fplbot.app/search/any?query=${encodeURIComponent(q)}&page=0&type=entries`;
    const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0 (fpl-squad-watch search)" } });

    if (!r.ok) {
      return res.status(200).json({ hits: [], note: "Name search is temporarily unavailable." });
    }

    const data = await r.json();
    const raw = (data.hits && data.hits.exposedHits) || [];
    const hits = raw
      .filter(h => h.type === "entry" && h.source && h.source.id)
      .slice(0, 8)
      .map(h => ({
        id: h.source.id,
        name: h.source.realName || "Unknown",
        teamName: h.source.teamName || "",
      }));

    res.setHeader("Cache-Control", "s-maxage=60, stale-while-revalidate=180");
    return res.status(200).json({ hits });
  } catch (err) {
    return res.status(200).json({ hits: [], note: "Name search is temporarily unavailable." });
  }
}
