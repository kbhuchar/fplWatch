// Vercel serverless function: look up any FPL team by entry ID and return it
// in the same shape as the manager profiles embedded in compare.html, so it
// can be dropped straight into the existing comparison UI.
//
// GET /api/team?id=1234567&gw=1

const BASE = "https://fantasy.premierleague.com/api";
const HEADERS = { "User-Agent": "Mozilla/5.0 (fpl-squad-watch lookup)" };
const POSITION_NAMES = { 1: "GKP", 2: "DEF", 3: "MID", 4: "FWD" };

export default async function handler(req, res) {
  const { id, gw } = req.query;

  if (!id || !/^\d+$/.test(String(id))) {
    return res.status(400).json({ error: "Enter a numeric FPL team ID, e.g. 1234567." });
  }

  try {
    const [entryRes, historyRes, bootstrapRes] = await Promise.all([
      fetch(`${BASE}/entry/${id}/`, { headers: HEADERS }),
      fetch(`${BASE}/entry/${id}/history/`, { headers: HEADERS }),
      fetch(`${BASE}/bootstrap-static/`, { headers: HEADERS }),
    ]);

    if (entryRes.status === 404) {
      return res.status(404).json({ error: "No FPL team found with that ID." });
    }
    if (!entryRes.ok || !historyRes.ok || !bootstrapRes.ok) {
      return res.status(502).json({ error: "FPL API request failed. Try again in a moment." });
    }

    const entry = await entryRes.json();
    const history = await historyRes.json();
    const bootstrap = await bootstrapRes.json();

    const teamShort = Object.fromEntries(bootstrap.teams.map(t => [t.id, t.short_name]));
    const players = Object.fromEntries(bootstrap.elements.map(p => [p.id, {
      name: p.web_name,
      team: teamShort[p.team] || "?",
      position: POSITION_NAMES[p.element_type] || "?",
    }]));

    let targetGw = gw ? parseInt(gw, 10) : null;
    if (!targetGw) {
      const current = bootstrap.events.find(e => e.is_current);
      const finished = bootstrap.events.filter(e => e.is_finished).map(e => e.id);
      targetGw = current ? current.id : (finished.length ? Math.max(...finished) : 1);
    }

    const picksRes = await fetch(`${BASE}/entry/${id}/event/${targetGw}/picks/`, { headers: HEADERS });
    if (!picksRes.ok) {
      return res.status(502).json({ error: `No picks found for gameweek ${targetGw}.` });
    }
    const picksData = await picksRes.json();

    const playerInfo = pid => players[pid] || { name: `#${pid}`, team: "?", position: "?" };
    const squad = picksData.picks.map(pk => ({ id: pk.element, ...playerInfo(pk.element) }));
    const startingIds = new Set(picksData.picks.filter(pk => pk.position <= 11).map(pk => pk.element));
    const startingXi = squad.filter(p => startingIds.has(p.id));
    const captainPick = picksData.picks.find(pk => pk.is_captain);
    const gwHistory = (history.current || []).find(h => h.event === targetGw);

    res.setHeader("Cache-Control", "s-maxage=120, stale-while-revalidate=300");
    return res.status(200).json({
      id: `custom:${id}`,
      label: `${entry.player_first_name} ${entry.player_last_name}`.trim(),
      team_name: entry.name,
      source: "custom",
      squad,
      starting_xi: startingXi,
      captain: captainPick ? playerInfo(captainPick.element) : null,
      transfers: gwHistory ? gwHistory.event_transfers : 0,
      transfer_cost: gwHistory ? gwHistory.event_transfers_cost : 0,
      gw_points: gwHistory ? gwHistory.points : null,
      active_chip: picksData.active_chip || null,
      current_gw: targetGw,
    });
  } catch (err) {
    return res.status(500).json({ error: "Something went wrong looking up that team." });
  }
}
