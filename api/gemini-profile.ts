// Vercel serverless function: per-company research profile from Gemini.
// POST { symbol, name, exchange, sector, context } -> { content, model }.
// Uses the "🗞 News" button on a company card; grounded with Google search.
// Uses the legacy (req, res) signature — the (req) => Response style is
// ignored by this runtime (returns get dropped, request hangs until timeout).
// Key: GOOGLE_GEMINI_API_KEY or GOOGLE_API_KEY (Vercel env).

const MODEL = "gemini-3.1-pro-preview";

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

// Grounded generation can take a while; stay under the 60s function cap.
const UPSTREAM_TIMEOUT_MS = 52_000;

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
      throw new Error(`Gemini API ${res.status}: ${text.slice(0, 300)}`);
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function postJson(url: string, headers: Record<string, string>, body: unknown): Promise<any> {
  return postJsonTimeout(url, headers, body, UPSTREAM_TIMEOUT_MS);
}

function generationPayload(prompt: string, seed: number, grounded: boolean) {
  const base = {
    contents: [
      {
        role: "user",
        parts: [{ text: prompt }],
      },
    ],
    generationConfig: {
      seed,
      maxOutputTokens: 3072,
      temperature: 0.3,
    },
  };
  if (grounded) {
    // google_search:{} is rejected by some 3.x preview models (400 "The string
    // did not match the expected pattern"); the retrieval form is accepted.
    return {
      ...base,
      tools: [
        {
          google_search_retrieval: {
            dynamic_retrieval_config: { mode: "MODE_DYNAMIC", dynamic_threshold: 0.3 },
          },
        },
      ],
    };
  }
  return base;
}

async function askGemini(key: string, prompt: string, grounded: boolean, timeoutMs: number) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${key}`;
  const data = await postJsonTimeout(
    url, {}, generationPayload(prompt, Date.now() % 1_000_000, grounded), timeoutMs,
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
    // Grounded first; if grounding is unsupported for this model/key, fall
    // back to plain generation so the profile always comes back.
    let result;
    try {
      result = await askGemini(key, buildPrompt(body), true, 38_000);
    } catch {
      result = await askGemini(key, buildPrompt(body), false, 20_000);
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