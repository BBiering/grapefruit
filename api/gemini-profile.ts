// Vercel serverless function: per-company research profile from Gemini,
// served through Google's Gemini Enterprise Agent Platform (aiplatform).
// POST { symbol, name, exchange, sector, context } -> { content, model }.
// Used by the "🗞 News" button. Auth: Google Cloud API key via x-goog-api-key
// (GOOGLE_GEMINI_API_KEY in Vercel env; project GOOGLE_CLOUD_PROJECT, default
// grapefruit-500208). Legacy (req, res) signature — this runtime ignores
// returned Response objects.

const MODEL = "gemini-3.1-pro-preview";
const PROJECT = process.env.GOOGLE_CLOUD_PROJECT || "grapefruit-500208";
const BASE = `https://aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/global/publishers/google/models/${MODEL}:generateContent`;

// Grounded generation can take a while; stay under the 60s function cap.
const GROUNDED_TIMEOUT_MS = 40_000;
const PLAIN_TIMEOUT_MS = 20_000;

interface Body {
  symbol?: string;
  name?: string;
  exchange?: string;
  sector?: string;
  context?: string;
}

interface ReqLike {
  method?: string;
  body?: unknown;
}

interface ResLike {
  status(code: number): ResLike;
  json(payload: unknown): void;
}

async function postJsonTimeout(url: string, headers: Record<string, string>, body: unknown, timeoutMs: number): Promise<any> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Gemini Agent Platform ${res.status}: ${text.slice(0, 300)}`);
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

function generationPayload(prompt: string, grounded: boolean) {
  const base = {
    contents: [
      {
        role: "user",
        parts: [{ text: prompt }],
      },
    ],
    // Note: reasoning tokens count against this budget on 3.x models.
    generationConfig: {
      maxOutputTokens: 3072,
      temperature: 0.3,
    },
  };
  if (grounded) {
    // Agent Platform accepts google_search; the googleSearchRetrieval variant
    // is rejected for this model ("please use google_search field instead").
    return { ...base, tools: [{ google_search: {} }] };
  }
  return base;
}

async function askGemini(key: string, prompt: string, grounded: boolean, timeoutMs: number) {
  const data = await postJsonTimeout(
    BASE,
    { "x-goog-api-key": key },
    generationPayload(prompt, grounded),
    timeoutMs,
  );
  const text = (data?.candidates?.[0]?.content?.parts ?? [])
    .map((p: any) => p.text ?? "")
    .join("")
    .trim();
  return { content: text, model: MODEL };
}

function buildPrompt(input: Body): string {
  const display = input.name && input.name !== input.symbol ? `${input.symbol} (${input.name})` : input.symbol ?? "";
  const contextLines = [
    `Today's date: ${new Date().toISOString().slice(0, 10)}`,
    input.exchange ? `Listed on: ${input.exchange}` : null,
    input.sector && input.sector !== "Unknown" ? `Sector: ${input.sector}` : null,
    input.context || null,
  ].filter(Boolean);

  return [
    "Act as a biotech equity research analyst. I am evaluating ",
    `${display} to assess its current clinical and financial setup. `,
    "Provide an objective, data-driven profile of the company focused strictly ",
    "on facts, metrics, and upcoming catalysts. Do not provide direct financial ",
    "advice or buy/sell recommendations.\n",
    "Please break down the response into the following 5 structured sections:\n",
    "1. Lead Assets & Clinical Pipeline Status\n",
    "    •    What is the primary drug candidate/asset, its target indication, and current clinical stage (e.g., Phase 2, Phase 3 BLA/NDA)?\n",
    "    •    What were the key endpoints, response rates, or efficacy metrics from the most recent trial readout?\n",
    "    •    What are the key competing therapies currently on the market or in late-stage development for the same indication?\n",
    "2. Immediate & Near-Term Regulatory Catalysts\n",
    "    •    Are there any upcoming PDUFA target action dates, AdCom/CHMP meetings, or major trial data readouts? State exact dates or estimated quarters.\n",
    "    •    Has the FDA or EMA granted special designations (e.g., Breakthrough Therapy, Orphan Drug, RMAT, Fast Track)?\n",
    "    •    Has the company received any recent regulatory setbacks, such as a Complete Response Letter (CRL), clinical hold, or negative panel vote?\n",
    "3. Balance Sheet & Cash Runway\n",
    "    •    What is the company’s current cash position (cash, cash equivalents, and marketable securities)?\n",
    "    •    What is the recent quarterly cash burn rate, and what is the estimated cash runway (in months/years)?\n",
    "    •    Has the company recently filed a shelf registration (S-3) or executed an offering? Is there an immediate risk of share dilution before the next major catalyst?\n",
    "4. Legal, IP, & Risk Headwinds\n",
    "    •    What is the patent expiration timeline for the lead asset?\n",
    "    •    Are there any active securities class-action lawsuits, regulatory investigations, or IP litigations affecting the company?\n",
    "5. Market Sentiment & Trading Metrics\n",
    "    •    What is the consensus Wall Street 12-month price target (low, average, high), and how recently were these targets updated (noting if they reflect recent catalyst events)?\n",
    "    •    What is the current level of institutional ownership and short interest percentage of the float?\n",
    "\nCompany context (from the Grapefruit dashboard) to ground your answer:\n",
    ...contextLines.map((l) => `- ${l}`),
    "\nUse live web search to verify figures and dates. Mark anything you could not verify as unverified.",
  ].join("\n");
}

export default async function handler(req: ReqLike, res: ResLike) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "method not allowed" });
  }
  let body: Body = {};
  try {
    body = (req.body ?? {}) as Body;
  } catch {
    return res.status(400).json({ error: "invalid json body" });
  }
  if (!body.symbol) {
    return res.status(400).json({ error: "symbol is required" });
  }

  const key = process.env.GOOGLE_GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
  if (!key) {
    return res.status(501).json({ error: "GOOGLE_GEMINI_API_KEY not configured in Vercel env" });
  }

  try {
    // Grounded first; fall back to plain generation so the profile always
    // comes back even if search grounding misbehaves.
    let result;
    try {
      result = await askGemini(key, buildPrompt(body), true, GROUNDED_TIMEOUT_MS);
    } catch {
      result = await askGemini(key, buildPrompt(body), false, PLAIN_TIMEOUT_MS);
    }
    if (!result.content) {
      return res.status(502).json({ error: "model returned an empty answer" });
    }
    return res.status(200).json(result);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return res.status(502).json({ error: `upstream failed: ${msg.slice(0, 300)}` });
  }
}