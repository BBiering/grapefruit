// Vercel serverless function: proxies browser chat to the Perplexity Agent API.
// Keeps PERPLEXITY_API_KEY server-side (never ship it in the SPA bundle).
// Deploy env var: PERPLEXITY_API_KEY (set in Vercel project settings).
// No external deps: Vercel compiles this .ts with its Node builder automatically.

interface ReqLike {
  method?: string;
  body?: unknown;
}

interface ResLike {
  status(code: number): ResLike;
  json(payload: unknown): void;
}

const AGENT_URL = "https://api.perplexity.ai/v1/agent";
const PRESET = "low"; // fast single-chat research tier with tools

interface ChatPayload {
  context: string;
  question: string;
}

export default async function handler(req: ReqLike, res: ResLike) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "method not allowed" });
  }

  const apiKey = process.env.PERPLEXITY_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: "server not configured (missing PERPLEXITY_API_KEY)" });
  }

  const { context = "", question = "" } = (req.body ?? {}) as ChatPayload;
  if (!question.trim()) {
    return res.status(400).json({ error: "question is required" });
  }

  const instructions = [
    "You are a biotech equity research assistant embedded in the Grapefruit dashboard.",
    "The user is looking at a company card. Use the provided card context, plus",
    "finance_search, web_search, and fetch_url, to give a grounded, specific answer.",
    "Cite sources by URL when you rely on them. Keep answers concise but information-dense.",
    "",
    "COMPANY CARD CONTEXT (pre-computed by the app):",
    context,
  ].join("\n");

  try {
    const upstream = await fetch(AGENT_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        preset: PRESET,
        input: question,
        instructions,
        tools: [
          { type: "finance_search" },
          { type: "web_search" },
          { type: "fetch_url" },
        ],
        max_steps: 8,
      }),
    });

    if (!upstream.ok) {
      const body = await upstream.text().catch(() => "");
      console.error(`perplexity agent ${upstream.status}: ${body.slice(0, 500)}`);
      return res.status(502).json({ error: `Perplexity returned ${upstream.status}` });
    }

    const data = (await upstream.json()) as {
      output?: Array<{
        content?: Array<{ type?: string; text?: string }>;
      }>;
    };

    // Extract the final assistant text from the Agent API response shape.
    const texts: string[] = [];
    for (const item of data.output ?? []) {
      for (const part of item.content ?? []) {
        if (part.type === "output_text" && typeof part.text === "string") {
          texts.push(part.text);
        }
      }
    }
    const answer = texts.join("").trim();

    if (!answer) {
      return res.status(502).json({ error: "Perplexity returned an empty answer" });
    }
    return res.status(200).json({ answer });
  } catch (err) {
    console.error("chat proxy error:", err);
    return res.status(500).json({ error: "chat proxy failed" });
  }
}
