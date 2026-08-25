// Vercel serverless function: resolve an entire FPL classic league into
// manager profiles shaped exactly like the ones already embedded on
// Head-to-Head, so an "added" league's managers can drop straight into
// the same picker as your home league, YouTubers, and looked-up teams.
//
// GET /api/league?id=587101&gw=1

const BASE = "https://fantasy.premierleague.com/api";
const HEADERS = { "User-Agent": "Mozilla/5.0 (fpl-squad-watch lookup)" };
const POSITION_NAMES = { 1: "GKP", 2: "DEF", 3: "MID", 4: "FWD" };
const MAX_ENTRIES = 20;
const BATCH_SIZE = 5;

export const config = { maxDuration: 60 };

export default async function handler(req, res) {
  const { id, gw } = req.query;

  if (!id || !/^\d+$/.test(String(id))) {
    return res.status(400).json({ error: "Enter a numeric league ID, e.g. 587101." });
  }

  try {
    const [standingsRes, bootstrapRes] = await Promise.all([
      fetch(`${BASE}/leagues-classic/${id}/standings/`, { headers: HEADERS }),
      fetch(`${BASE}/bootstrap-static/`, { headers: HEADERS }),
    ]);

    if (standingsRes.status === 404) {
      return res.status(404).json({ error: "No league found with that ID." });
    }
    if (!standingsRes.ok || !bootstrapRes.ok) {
      return res.status(502).json({ error: "FPL API request failed. Try again in a moment." });
    }

    const standings = await standingsRes.json();
    const bootstrap = await bootstrapRes.json();

    const leagueName = standings.league?.name || `League ${id}`;
    let entries = standings.standings?.results || [];
    const truncated = entries.length > MAX_ENTRIES;
    entries = entries.slice(0, MAX_ENTRIES);

    if (!entries.length) {
      return res.status(404).json({ error: "That league has no members yet." });
    }

    const teamShort = Object.fromEntries(bootstrap.teams.map((t) => [t.id, t.short_name]));
    const players = Object.fromEntries(
      bootstrap.elements.map((p) => [
        p.id,
        { name: p.web_name, team: teamShort[p.team] || "?", position: POSITION_NAMES[p.element_type] || "?" },
      ]),
    );
    const playerInfo = (pid) => players[pid] || { name: `#${pid}`, team: "?", position: "?" };

    let targetGw = gw ? parseInt(gw, 10) : null;
    if (!targetGw) {
      const current = bootstrap.events.find((e) => e.is_current);
      const finished = bootstrap.events.filter((e) => e.is_finished).map((e) => e.id);
      targetGw = current ? current.id : finished.length ? Math.max(...finished) : 1;
    }

    async function fetchManager(entry) {
      try {
        const [historyRes, picksRes] = await Promise.all([
          fetch(`${BASE}/entry/${entry.entry}/history/`, { headers: HEADERS }),
          fetch(`${BASE}/entry/${entry.entry}/event/${targetGw}/picks/`, { headers: HEADERS }),
        ]);
        if (!historyRes.ok || !picksRes.ok) return null;

        const history = await historyRes.json();
        const picksData = await picksRes.json();
        const gwHistory = (history.current || []).find((h) => h.event === targetGw);

        const squad = picksData.picks.map((pk) => ({ id: pk.element, ...playerInfo(pk.element) }));
        const startingIds = new Set(picksData.picks.filter((pk) => pk.position <= 11).map((pk) => pk.element));
        const startingXi = squad.filter((p) => startingIds.has(p.id));
        const captainPick = picksData.picks.find((pk) => pk.is_captain);

        return {
          id: `league-${id}:${entry.entry}`,
          label: entry.player_name,
          team_name: entry.entry_name,
          source: `league-${id}`,
          squad,
          starting_xi: startingXi,
          captain: captainPick ? playerInfo(captainPick.element) : null,
          transfers: gwHistory ? gwHistory.event_transfers : 0,
          transfer_cost: gwHistory ? gwHistory.event_transfers_cost : 0,
          gw_points: gwHistory ? gwHistory.points : null,
          active_chip: picksData.active_chip || null,
        };
      } catch (err) {
        return null;
      }
    }

    const managers = [];
    for (let i = 0; i < entries.length; i += BATCH_SIZE) {
      const batch = entries.slice(i, i + BATCH_SIZE);
      const results = await Promise.all(batch.map(fetchManager));
      managers.push(...results.filter(Boolean));
    }

    if (!managers.length) {
      return res.status(502).json({ error: "Couldn't load any managers from that league. Try again." });
    }

    res.setHeader("Cache-Control", "s-maxage=120, stale-while-revalidate=300");
    return res.status(200).json({
      league_id: Number(id),
      league_name: leagueName,
      current_gw: targetGw,
      truncated,
      managers,
    });
  } catch (err) {
    return res.status(500).json({ error: "Something went wrong loading that league." });
  }
}
