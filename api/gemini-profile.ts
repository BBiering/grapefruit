// Vercel serverless function: per-company research profile from Gemini.
// POST { symbol, name, exchange, sector, context } -> { content, model }.
// Uses the "🗞 News" button on a company card. Web grounding where available,
// plain-completion fallback otherwise. Key: GOOGLE_GEMINI_API_KEY or
// GOOGLE_API_KEY (Vercel env).

const MODEL = "gemini-3.1-pro-preview";

interface Body {
  symbol?: string;
  name?: string;
  exchange?: string;
  sector?: string;
  context?: string;
}

async function postJson(url: string, headers: Record<string, string>, body: unknown): Promise<any> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 90_000);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`${res.status}: ${text.slice(0, 300)}`);
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function askGemini(key: string, prompt: string, withSearch: boolean) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${key}`;
  const base = {
    contents: [
      {
        role: "user",
        parts: [{ text: prompt }],
      },
    ],
    generationConfig: {
      maxOutputTokens: 4096,
      temperature: 0.3,
    },
  };
  const payload = withSearch ? { ...base, tools: [{ google_search: {} }] } : base;
  const data = await postJson(url, {}, payload);
  const text = (data?.candidates?.[0]?.content?.parts ?? [])
    .map((p: any) => p.text ?? "")
    .join("")
    .trim();
  return { content: text, model: MODEL, used_search: withSearch };
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

export default async function handler(req: Request) {
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "method not allowed" }), { status: 405 });
  }
  let body: Body = {};
  try {
    body = (await req.json()) as Body;
  } catch {
    return new Response(JSON.stringify({ error: "invalid json body" }), { status: 400 });
  }
  if (!body.symbol) {
    return new Response(JSON.stringify({ error: "symbol is required" }), { status: 400 });
  }

  const key = process.env.GOOGLE_GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
  if (!key) {
    return new Response(
      JSON.stringify({ error: "GOOGLE_GEMINI_API_KEY not configured in Vercel env" }),
      { status: 501 },
    );
  }

  const prompt = buildPrompt(body);
  try {
    let result;
    try {
      result = await askGemini(key, prompt, true);
    } catch {
      result = await askGemini(key, prompt, false);
    }
    if (!result.content) {
      return new Response(JSON.stringify({ error: "model returned an empty answer" }), { status: 502 });
    }
    return new Response(JSON.stringify(result), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return new Response(
      JSON.stringify({ error: `upstream failed: ${err instanceof Error ? err.message.slice(0, 300) : String(err)}` }),
      { status: 502 },
    );
  }
}