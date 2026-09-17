// Vercel serverless function: latest news + investment pros/cons for a stock,
// from one of three LLM providers (ChatGPT / Claude / Gemini). Web search is
// enabled per provider where available, with a plain-completion fallback.
// No external deps. Keys via env: OPENAI_API_KEY, ANTHROPIC_API_KEY,
// GOOGLE_GEMINI_API_KEY (missing key => 501 per provider).

interface Body {
  provider?: string;
  symbol?: string;
  name?: string;
  exchange?: string;
  sector?: string;
  context?: string;
}

const PROVIDER_KEYS: Record<string, string> = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  gemini: "GOOGLE_GEMINI_API_KEY",
};

async function postJson(url: string, headers: Record<string, string>, body: unknown): Promise<any> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 60_000);
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

async function askOpenAI(key: string, prompt: string) {
  const base = {
    model: "gpt-4.1-mini",
    messages: [
      { role: "system", content: "You are a concise biotech equity research assistant. Follow the requested format." },
      { role: "user", content: prompt },
    ],
    temperature: 0.3,
  };
  try {
    const data = await postJson(
      "https://api.openai.com/v1/chat/completions",
      { Authorization: `Bearer ${key}` },
      { ...base, tools: [{ type: "web_search" }] },
    );
    return { content: data.choices?.[0]?.message?.content ?? "", model: "gpt-4.1-mini", used_search: true };
  } catch {
    const data = await postJson("https://api.openai.com/v1/chat/completions", { Authorization: `Bearer ${key}` }, base);
    return { content: data.choices?.[0]?.message?.content ?? "", model: "gpt-4.1-mini", used_search: false };
  }
}

async function askAnthropic(key: string, prompt: string) {
  const base = {
    model: "claude-sonnet-4-5",
    max_tokens: 1500,
    system: "You are a concise biotech equity research assistant. Follow the requested format.",
    messages: [{ role: "user", content: prompt }],
  };
  const headers = { "x-api-key": key, "anthropic-version": "2023-06-01" };
  try {
    const data = await postJson(
      "https://api.anthropic.com/v1/messages",
      { ...headers, "anthropic-beta": "web-search-20250305" },
      { ...base, tools: [{ type: "web_search_20250305" }] },
    );
    const text = (data.content ?? []).filter((b: any) => b.type === "text").map((b: any) => b.text).join("");
    return { content: text, model: "claude-sonnet-4-5", used_search: true };
  } catch {
    const data = await postJson("https://api.anthropic.com/v1/messages", headers, base);
    const text = (data.content ?? []).filter((b: any) => b.type === "text").map((b: any) => b.text).join("");
    return { content: text, model: "claude-sonnet-4-5", used_search: false };
  }
}

async function askGemini(key: string, prompt: string) {
  const model = "gemini-2.5-flash";
  const url = (withSearch: boolean) =>
    `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${key}` +
    (withSearch ? "" : "");
  const base = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: { maxOutputTokens: 1500 },
  };
  try {
    const data = await postJson(url(true), {}, { ...base, tools: [{ google_search: {} }] });
    const text = (data?.candidates?.[0]?.content?.parts ?? []).map((p: any) => p.text ?? "").join("");
    return { content: text, model, used_search: true };
  } catch {
    const data = await postJson(url(false), {}, base);
    const text = (data?.candidates?.[0]?.content?.parts ?? []).map((p: any) => p.text ?? "").join("");
    return { content: text, model, used_search: false };
  }
}

function buildPrompt(input: Body): string {
  const { symbol, name, exchange, sector, context } = input;
  const company = name && name !== symbol ? `${name} (${symbol})` : symbol;
  return [
    `Today is ${new Date().toISOString().slice(0, 10)}. You are a biotech equity research assistant.`,
    `Research the latest news about ${company}` +
      (exchange ? `, listed on ${exchange}` : "") +
      (sector && sector !== "Unknown" ? `, sector ${sector}` : "") +
      ".",
    context ? `Context already known about this company:\n${context}` : "",
    "Use live web search. Then give a short investment assessment with exactly these three sections:",
    "## Latest news",
    "(bullet list of the 3-5 most relevant recent items, each with a date)",
    "## Bull case (pros)",
    "## Bear case (cons)",
    "Cite sources by URL when you rely on them. Mark anything you could not verify as unverified. If you cannot reach live search, say so and answer from general knowledge only.",
  ].filter(Boolean).join("\n");
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

  const provider = body.provider;
  if (!provider || !PROVIDER_KEYS[provider]) {
    return new Response(JSON.stringify({ error: "unknown provider" }), { status: 400 });
  }
  if (!body.symbol) {
    return new Response(JSON.stringify({ error: "symbol is required" }), { status: 400 });
  }

  const key = process.env[PROVIDER_KEYS[provider]];
  if (!key) {
    return new Response(
      JSON.stringify({ error: `${PROVIDER_KEYS[provider]} not configured in Vercel env` }),
      { status: 501 },
    );
  }

  const prompt = buildPrompt(body);
  try {
    const result =
      provider === "openai" ? await askOpenAI(key, prompt)
      : provider === "anthropic" ? await askAnthropic(key, prompt)
      : await askGemini(key, prompt);
    if (!result.content.trim()) {
      return new Response(JSON.stringify({ error: "model returned an empty answer" }), { status: 502 });
    }
    return new Response(JSON.stringify({ provider, ...result }), {
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