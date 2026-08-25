// Vercel serverless function: answers plain-English questions about the
// league by handing Claude the same JSON already embedded in Squad Watch
// (standings, squad overlap, most-owned players, captains, the captain
// leaderboard, transfers/chips) and letting it reason over real numbers.
//
// POST /api/analyst  { question: string, data: object }

import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic();

const MAX_DATA_CHARS = 60000;
const MAX_QUESTION_CHARS = 500;

const SYSTEM_PROMPT = `You are the League Analyst for an FPL (Fantasy Premier League) fan site. You answer questions about one specific classic mini-league using ONLY the JSON data provided in the next system block.

The data includes:
- standings: season points and rank per manager
- overlap_matrix: how similar each manager's squad is to every other manager's
- most_owned: players owned across the league and by whom
- captains: this gameweek's captain pick per manager
- captain_leaderboard: cumulative points earned from captaincy all season, ranked, with who each manager captains most and their average per gameweek
- transfers: this gameweek's transfer activity, hits taken, and active chips
- youtubers: slots for linked FPL YouTubers (may be unlinked)

Rules:
- Answer directly and conversationally, like a knowledgeable friend, not a report. A few sentences is usually enough -- use a short list only if the question genuinely calls for one.
- Back up your answer with specific names and numbers from the data.
- If the data doesn't contain what's needed to answer -- a historical trend that isn't tracked, a stat that isn't computed, a team that isn't in this league -- say so plainly. Never invent players, points, or managers.
- The season may still be early (few gameweeks played) -- if a question assumes more history than exists, note that briefly instead of pretending otherwise.`;

export const config = { maxDuration: 60 };

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Use POST." });
  }

  const requiredPasscode = process.env.ANALYST_PASSCODE;
  if (requiredPasscode) {
    const provided = req.headers["x-analyst-passcode"];
    if (provided !== requiredPasscode) {
      return res.status(401).json({ error: "Incorrect passcode." });
    }
  }

  if (!process.env.ANTHROPIC_API_KEY) {
    return res.status(500).json({ error: "The analyst isn't configured yet (missing API key)." });
  }

  const { question, data } = req.body || {};

  if (typeof question !== "string" || !question.trim()) {
    return res.status(400).json({ error: "Ask a question." });
  }
  if (question.length > MAX_QUESTION_CHARS) {
    return res.status(400).json({ error: "That question's too long -- try to keep it under 500 characters." });
  }
  if (!data || typeof data !== "object") {
    return res.status(400).json({ error: "Missing league data." });
  }

  const dataStr = JSON.stringify(data);
  if (dataStr.length > MAX_DATA_CHARS) {
    return res.status(400).json({ error: "League data payload is too large." });
  }

  try {
    const response = await client.messages.create({
      model: "claude-opus-5",
      max_tokens: 1500,
      output_config: { effort: "medium" },
      system: [
        { type: "text", text: SYSTEM_PROMPT, cache_control: { type: "ephemeral" } },
        {
          type: "text",
          text: `Here is the current league data as JSON:\n${dataStr}`,
          cache_control: { type: "ephemeral" },
        },
      ],
      messages: [{ role: "user", content: question.trim() }],
    });

    if (response.stop_reason === "refusal") {
      return res.status(200).json({ answer: "I can't answer that one -- try rephrasing it." });
    }

    const textBlock = response.content.find((b) => b.type === "text");
    return res.status(200).json({ answer: textBlock ? textBlock.text : "" });
  } catch (err) {
    if (err instanceof Anthropic.AuthenticationError) {
      return res.status(500).json({ error: "The analyst isn't configured correctly (invalid API key)." });
    }
    if (err instanceof Anthropic.RateLimitError) {
      return res.status(429).json({ error: "The analyst is busy -- try again in a moment." });
    }
    return res.status(502).json({ error: "The analyst request failed. Try again." });
  }
}
