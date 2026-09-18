// Vercel serverless function: per-company research profile from Gemini,
// served through Google's Gemini Enterprise Agent Platform (aiplatform).
// POST { symbol, name, exchange, sector, context } -> streams NDJSON deltas:
//   {"d":"<incremental text>"}  ...  EOF  |  {"error":"..."}
// Used by the "🗞 News" button. Auth: Google Cloud API key via x-goog-api-key
// (GOOGLE_GEMINI_API_KEY in Vercel env; project GOOGLE_CLOUD_PROJECT, default
// grapefruit-500208). Legacy (req, res) signature — this runtime ignores
// returned Response objects and streams via res.write().

const MODEL = "gemini-3.1-pro-preview";
const PROJECT = process.env.GOOGLE_CLOUD_PROJECT || "grapefruit-500208";
const BASE = `https://aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/global/publishers/google/models/${MODEL}:generateContent`;

const GROUNDED_TIMEOUT_MS = 58_000;
const PLAIN_FALLBACK_TIMEOUT_MS = 45_000;

interface Body {
  symbol?: string;
  name?: string;
  exchange?: string;
  sector?: string;
  context?: string;
}

interface ReqLike { method?: string; body?: unknown; }
interface ResLike {
  writeHead(code: number, headers: Record<string, string>): void;
  write(chunk: string): void;
  end(): void;
}
interface Progress { written: number; }

function generationPayload(prompt: string, grounded: boolean) {
  const base = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    // Trimmed generation: capped output + modest thinking budget keep the whole
    // grounded run under the 60s function limit (TTFT is ~20s regardless).
    generationConfig: {
      maxOutputTokens: 2048,
      temperature: 0.3,
      thinkingConfig: { thinkingBudget: 256 },
    },
  };
  if (grounded) {
    // Agent Platform accepts google_search; googleSearchRetrieval is rejected
    // for this model ("please use google_search field instead").
    return { ...base, tools: [{ google_search: {} }] };
  }
  return base;
}

// Streams the SSE generateContent response and forwards every new text chunk
// as a NDJSON delta. Note: on this surface the SSE parts carry INCREMENTAL
// text (deltas), not the full accumulated answer.
async function streamGemini(
  key: string,
  prompt: string,
  grounded: boolean,
  res: ResLike,
  timeoutMs: number,
  progress: Progress,
): Promise<void> {
  const url = BASE.replace(":generateContent", ":streamGenerateContent") + "?alt=sse";
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": key },
      body: JSON.stringify(generationPayload(prompt, grounded)),
      signal: ctrl.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    throw err;
  }
  try {
    if (!upstream.ok || !upstream.body) {
      const text = await upstream.text().catch(() => "");
      throw new Error(`Gemini Agent Platform ${upstream.status}: ${text.slice(0, 300)}`);
    }
    const reader = upstream.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() ?? "";
      for (const line of lines) {
        const t = line.trim();
        if (!t.startsWith("data:")) continue;
        const payload = t.slice(5).trim();
        if (!payload || payload === "[DONE]") continue;
        let chunk: any;
        try { chunk = JSON.parse(payload); } catch { continue; }
        const text = (chunk?.candidates?.[0]?.content?.parts ?? [])
          .map((p: any) => p.text ?? "")
          .join("");
        if (text) {
          progress.written += text.length;
          res.write(JSON.stringify({ d: text }) + "\n");
        }
      }
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`generation exceeded ${Math.round(timeoutMs / 1000)}s`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
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
    res.writeHead(405, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ error: "method not allowed" }));
  }
  let body: Body = {};
  try {
    body = (req.body ?? {}) as Body;
  } catch {
    res.writeHead(400, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ error: "invalid json body" }));
  }
  if (!body.symbol) {
    res.writeHead(400, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ error: "symbol is required" }));
  }

  const key = process.env.GOOGLE_GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
  if (!key) {
    res.writeHead(501, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ error: "GOOGLE_GEMINI_API_KEY not configured in Vercel env" }));
  }

  res.writeHead(200, { "Content-Type": "application/x-ndjson" });
  const prompt = buildPrompt(body);
  const progress: Progress = { written: 0 };
  const failMsg = (err: unknown) =>
    `upstream failed: ${err instanceof Error ? err.message.slice(0, 300) : String(err)}`;

  try {
    await streamGemini(key, prompt, true, res, GROUNDED_TIMEOUT_MS, progress);
  } catch (err) {
    // If partial text already reached the client, don't duplicate it with a
    // retry; just note the interruption.
    if (progress.written > 0) {
      res.write(JSON.stringify({ error: `stream interrupted: ${failMsg(err)}` }) + "\n");
    } else {
      try {
        await streamGemini(key, prompt, false, res, PLAIN_FALLBACK_TIMEOUT_MS, progress);
      } catch (err2) {
        res.write(JSON.stringify({ error: failMsg(err2) }) + "\n");
      }
    }
  }

  if (progress.written === 0) {
    res.write(JSON.stringify({ error: "model returned an empty answer" }) + "\n");
  }
  res.end();
}