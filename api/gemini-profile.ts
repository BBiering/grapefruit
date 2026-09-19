// Vercel serverless function: per-company research profile from Gemini.
// 1. Serves a cached profile from `company_news` when fresh (<24h).
// 2. Otherwise streams Gemini (Gemini Enterprise Agent Platform) as NDJSON
//    deltas and stores the result:  {"s": sent, "flags": [..]} {"d":"..."} ...
// Auth for Gemini: Google Cloud API key via x-goog-api-key (GOOGLE_GEMINI_API_KEY
// in Vercel env; project GOOGLE_CLOUD_PROJECT, default grapefruit-500208).
// Legacy (req, res) signature — this runtime ignores returned Response objects.

const MODEL = "gemini-3.1-pro-preview";
const PROJECT = process.env.GOOGLE_CLOUD_PROJECT || "grapefruit-500208";
const BASE = `https://aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/global/publishers/google/models/${MODEL}:generateContent`;

const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const GROUNDED_TIMEOUT_MS = 58_000;
const PLAIN_FALLBACK_TIMEOUT_MS = 45_000;

type Sentiment = "positive" | "negative" | "neutral";

interface Body { symbol?: string; name?: string; exchange?: string; sector?: string; context?: string; }
interface ReqLike { method?: string; body?: unknown; }
interface ResLike { writeHead(code: number, headers: Record<string, string>): void; write(chunk: string): void; end(): void; }
interface Progress { written: number; }

// ---------------------------------------------------------------------------
// Supabase REST (service role) for the company_news cache
// ---------------------------------------------------------------------------
function supabaseEnv() {
  const url = process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  return url && key ? { url, key } : null;
}

async function fetchCachedNews(symbol: string): Promise<{ content: string; sentiment: Sentiment; flags: string[] } | null> {
  const sb = supabaseEnv();
  if (!sb) return null;
  const api = `${sb.url}/rest/v1/company_news?symbol=eq.${encodeURIComponent(symbol)}&select=symbol,content,sentiment,red_flags,fetched_at`;
  const res = await fetch(api, {
    headers: { apikey: sb.key, Authorization: `Bearer ${sb.key}` },
  });
  if (!res.ok) return null;
  const rows = (await res.json()) as Array<{ content?: string; sentiment?: string | null; red_flags?: string | null; fetched_at?: string }>;
  const row = rows[0];
  if (!row || !row.content) return null;
  if (row.fetched_at && Date.now() - Date.parse(row.fetched_at) > CACHE_TTL_MS) return null; // stale
  return {
    content: row.content,
    sentiment: (row.sentiment as Sentiment) || "neutral",
    flags: (row.red_flags || "").split("|").map((s) => s.trim()).filter(Boolean).slice(0, 3),
  };
}

async function storeCachedNews(symbol: string, content: string, sentiment: Sentiment, flags: string[]) {
  const sb = supabaseEnv();
  if (!sb || !content.trim()) return;
  const body = {
    symbol,
    content,
    sentiment,
    red_flags: flags.slice(0, 3).join(" | "),
    model: MODEL,
    fetched_at: new Date().toISOString(),
  };
  const res = await fetch(`${sb.url}/rest/v1/company_news?on_conflict=symbol`, {
    method: "POST",
    headers: {
      apikey: sb.key,
      Authorization: `Bearer ${sb.key}`,
      "Content-Type": "application/json",
      Prefer: "resolution=merge-duplicates",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    // Cache miss on write: log-and-continue; the profile still streams.
    console.error("cache store failed:", res.status, await res.text().catch(() => ""));
  }
}

// ---------------------------------------------------------------------------
// Gemini streaming
// ---------------------------------------------------------------------------
function generationPayload(prompt: string, grounded: boolean) {
  const base = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: { maxOutputTokens: 4096, temperature: 0.3, thinkingConfig: { thinkingBudget: 128 } },
  };
  if (grounded) return { ...base, tools: [{ google_search: {} }] };
  return base;
}

async function streamGemini(
  key: string,
  prompt: string,
  grounded: boolean,
  res: ResLike,
  timeoutMs: number,
  progress: Progress,
  sink: string[],
) {
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
        const text = (chunk?.candidates?.[0]?.content?.parts ?? []).map((p: any) => p.text ?? "").join("");
        if (text) {
          progress.written += text.length;
          sink.push(text);
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

// The model ends its reply with two sentinel lines; strip them from the
// displayed text and return the parsed metadata.
function parseSentimentAndFlags(text: string): { clean: string; sentiment: Sentiment; flags: string[] } {
  let clean = text;
  let sentiment: Sentiment = "neutral";
  const sm = /SENTIMENT\s*:\s*(positive|negative|neutral)/i.exec(clean);
  if (sm) sentiment = sm[1].toLowerCase() as Sentiment;
  const fm = /RED\s*FLAGS?\s*:\s*([^\n]*)/i.exec(clean);
  const flags = fm
    ? fm[1].split(/[|\n;•–,]/).map((s) => s.trim().replace(/^[-*]\s*/, "")).filter((x) => x && !/^none$/i.test(x)).slice(0, 3)
    : [];
  clean = clean
    .replace(/SENTIMENT\s*:\s*[^\n]*\n?/i, "")
    .replace(/RED\s*FLAGS?\s*:\s*[^\n]*\n?/i, "")
    .trim();
  return { clean, sentiment, flags };
}

// ---------------------------------------------------------------------------
// Prompt
// ---------------------------------------------------------------------------
function buildPrompt(input: Body): string {
  const display = input.name && input.name !== input.symbol ? `${input.symbol} (${input.name})` : input.symbol ?? "";
  const lastClose = /Last close:\s*\$?([\d,]+(?:\.\d+)?)/i.exec(input.context || "")?.[1] ?? "?";
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
    "    •    What is the primary drug candidate/asset, its target indication, and current clinical stage?\n",
    "    •    What were the key endpoints, response rates, or efficacy metrics from the most recent trial readout?\n",
    "    •    What are the key competing therapies currently on the market or in late-stage development?\n",
    "2. Immediate & Near-Term Regulatory Catalysts\n",
    "    •    Are there any upcoming PDUFA target action dates, AdCom/CHMP meetings, or major trial data readouts? State exact dates or estimated quarters.\n",
    "    •    Has the FDA or EMA granted special designations (e.g., Breakthrough Therapy, Orphan Drug, RMAT, Fast Track)?\n",
    "    •    Has the company received any recent regulatory setbacks (CRL, clinical hold, negative panel vote)?\n",
    "3. Balance Sheet & Cash Runway\n",
    "    •    What is the company's current cash position (cash, cash equivalents, marketable securities)?\n",
    "    •    What is the recent quarterly cash burn rate, and what is the estimated cash runway (in months/years)?\n",
    "    •    Has the company recently filed a shelf registration (S-3) or executed an offering? Immediate dilution risk?\n",
    "4. Legal, IP, & Risk Headwinds\n",
    "    •    What is the patent expiration timeline for the lead asset?\n",
    "    •    Are there any active securities class-action lawsuits, regulatory investigations, or IP litigations?\n",
    `5. Market Sentiment & Trading Metrics — Current price: $${lastClose} | Wall Street 12-month consensus target: <fill from your research>\n`,
    "    •    What is the consensus Wall Street 12-month price target (low, average, high), and how recently updated?\n",
    "    •    What is the current level of institutional ownership and short interest percentage of the float?\n",
    "\nCompany context (from the Grapefruit dashboard) to ground your answer:\n",
    ...contextLines.map((l) => `- ${l}`),
    "\nUse live web search to verify figures and dates. Mark anything you could not verify as unverified.",
    "\n\nAt the very end of your reply, add exactly two final lines:",
    "SENTIMENT: POSITIVE|NEGATIVE|NEUTRAL (an overall sentiment on investing in this stock now)",
    "RED FLAGS: - flag one; - flag two; - flag three (each a short real risk; write 'none' if there are none)",
  ].join("\n");
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------
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

  // 1) Serve the cache when fresh.
  const cached = await fetchCachedNews(body.symbol);
  if (cached) {
    res.writeHead(200, { "Content-Type": "application/x-ndjson" });
    res.write(JSON.stringify({ s: cached.sentiment, flags: cached.flags }) + "\n");
    res.write(JSON.stringify({ d: cached.content }) + "\n");
    res.end();
    return;
  }

  const key = process.env.GOOGLE_GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
  if (!key) {
    res.writeHead(501, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ error: "GOOGLE_GEMINI_API_KEY not configured in Vercel env" }));
  }

  // 2) Live generation, streamed; accumulate for the cache write at the end.
  res.writeHead(200, { "Content-Type": "application/x-ndjson" });
  const fail = (label: string, err: unknown) => {
    const msg = err instanceof Error ? err.message : String(err);
    res.write(JSON.stringify({ error: `${label}: ${msg.slice(0, 300)}` }) + "\n");
    res.end();
  };

  const chunks: string[] = [];
  const progress: Progress = { written: 0 };
  try {
    await streamGemini(key, buildPrompt(body), true, res, GROUNDED_TIMEOUT_MS, progress, chunks);
  } catch (err) {
    if (progress.written === 0) {
      try {
        await streamGemini(key, buildPrompt(body), false, res, PLAIN_FALLBACK_TIMEOUT_MS, progress, chunks);
      } catch (err2) {
        fail("upstream failed", err2);
        return;
      }
    } else {
      res.write(JSON.stringify({ error: `stream interrupted: ${err instanceof Error ? err.message : err}` }) + "\n");
      res.end();
      return;
    }
  }

  if (progress.written === 0) {
    res.write(JSON.stringify({ error: "model returned an empty answer" }) + "\n");
    res.end();
    return;
  }

  const { clean, sentiment, flags } = parseSentimentAndFlags(chunks.join(""));
  res.write(JSON.stringify({ s: sentiment, flags }) + "\n");
  res.end();

  // 3) Cache it (fire-and-forget; profile already streamed).
  void storeCachedNews(body.symbol, clean, sentiment, flags);
}