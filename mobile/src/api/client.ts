import AsyncStorage from './storage';

const DEFAULT_BASE = 'http://localhost:8000';
const DEFAULT_TIMEOUT_MS = 30_000;
const SCAN_TIMEOUT_MS = 120_000;
const LONG_TIMEOUT_MS = 600_000;

export async function getBaseUrl(): Promise<string> {
  return (await AsyncStorage.getItem('apiBaseUrl')) || DEFAULT_BASE;
}

export async function setBaseUrl(url: string): Promise<void> {
  await AsyncStorage.setItem('apiBaseUrl', url.replace(/\/$/, ''));
}

const OWNER_SECRET_KEY = 'ownerSecret';

/** Owner API secret — SecureStore only; never log the value. */
export async function getOwnerSecret(): Promise<string> {
  return (await AsyncStorage.getItem(OWNER_SECRET_KEY)) || '';
}

export async function setOwnerSecret(secret: string): Promise<void> {
  const v = (secret || '').trim();
  if (!v) await AsyncStorage.removeItem(OWNER_SECRET_KEY);
  else await AsyncStorage.setItem(OWNER_SECRET_KEY, v);
}

/** True when a non-empty owner secret is stored (API secured from the client side). */
export async function hasOwnerSecret(): Promise<boolean> {
  return !!(await getOwnerSecret());
}

export function isLocalApiHost(url: string): boolean {
  try {
    const u = new URL(url);
    const h = (u.hostname || '').toLowerCase();
    return h === 'localhost' || h === '127.0.0.1' || h === '::1' || h === '10.0.2.2';
  } catch {
    return /localhost|127\.0\.0\.1/i.test(url || '');
  }
}

type ReqInit = RequestInit & { timeoutMs?: number };

function formatHttpError(status: number, detail: string, base: string, path: string): string {
  const short = (detail || '').trim().slice(0, 240) || 'No details';
  if (status === 404) return `Not found (${path}) on ${base}`;
  if (status === 401) return `Unauthorized — set Owner secret in Settings (X-Owner-Secret). ${short}`;
  if (status === 403) return `Forbidden (${status}): ${short}`;
  if (status === 429) return `Rate limited — wait a moment and retry. ${short}`;
  if (status >= 500) return `Server error (${status}) at ${base}${path}: ${short}`;
  return `API ${status} on ${path}: ${short}`;
}

function mergeSignals(timeoutMs: number, external?: AbortSignal | null): { signal: AbortSignal; cleanup: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onExternal = () => controller.abort();
  if (external) {
    if (external.aborted) controller.abort();
    else external.addEventListener('abort', onExternal, { once: true });
  }
  return {
    signal: controller.signal,
    cleanup: () => {
      clearTimeout(timer);
      if (external) external.removeEventListener('abort', onExternal);
    },
  };
}

async function req<T>(path: string, init?: ReqInit): Promise<T> {
  const base = await getBaseUrl();
  const timeoutMs = init?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const { timeoutMs: _t, signal: externalSignal, ...rest } = init || {};
  const { signal, cleanup } = mergeSignals(timeoutMs, externalSignal);

  try {
    const secret = await getOwnerSecret();
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(rest.headers as Record<string, string> | undefined),
    };
    if (secret) headers['X-Owner-Secret'] = secret;

    const doFetch = () =>
      fetch(`${base}${path}`, {
        ...rest,
        signal,
        headers,
      });

    let res: Response;
    try {
      res = await doFetch();
    } catch (first: any) {
      // One quick retry for flaky LAN (owner convenience)
      if (first?.name === 'AbortError') throw first;
      await new Promise((r) => setTimeout(r, 400));
      res = await doFetch();
    }
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text);
        if (typeof j?.detail === 'string') detail = j.detail;
        else if (Array.isArray(j?.detail)) detail = j.detail.map((d: any) => d?.msg || JSON.stringify(d)).join('; ');
        else if (j?.message) detail = j.message;
      } catch {
        /* keep raw text */
      }
      throw new Error(formatHttpError(res.status, detail, base, path));
    }
    if (res.status === 204) return undefined as T;
    const ct = res.headers.get('content-type') || '';
    if (!ct.includes('application/json')) {
      const text = await res.text();
      if (!text) return undefined as T;
      try {
        return JSON.parse(text) as T;
      } catch {
        throw new Error(`Expected JSON from ${base}${path}, got: ${text.slice(0, 120)}`);
      }
    }
    return (await res.json()) as T;
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      if (externalSignal?.aborted) {
        const err = new Error('Aborted');
        (err as any).name = 'AbortError';
        throw err;
      }
      throw new Error(
        `Timed out after ${Math.round(timeoutMs / 1000)}s — is the API running at ${base}?`,
      );
    }
    const msg = String(e?.message || e || '');
    if (
      /network request failed|failed to fetch|could not connect|connection refused|ECONNREFUSED/i.test(
        msg,
      )
    ) {
      throw new Error(
        `Cannot reach API at ${base}${path}. Check Settings → API base URL and that the server is running.`,
      );
    }
    throw e instanceof Error ? e : new Error(msg);
  } finally {
    cleanup();
  }
}

export const api = {
  health: () => req<{ status: string }>('/health'),
  getConfig: () => req<Record<string, any>>('/config'),
  putConfig: (body: Record<string, any>) =>
    req<Record<string, any>>('/config', { method: 'PUT', body: JSON.stringify(body) }),
  scan: () =>
    req<{ signals: any[]; watchlist: string[]; news_impact?: any[] }>('/scan', {
      method: 'POST',
      timeoutMs: SCAN_TIMEOUT_MS,
    }),
  signals: () => req<{ signals: any[] }>('/signals'),
  signal: (t: string) => req<any>(`/signals/${t}`),
  portfolio: () => req<any>('/portfolio'),
  order: (body: any) =>
    req<any>('/portfolio/orders', { method: 'POST', body: JSON.stringify(body) }),
  close: (id: string) => req<any>(`/portfolio/close/${id}`, { method: 'POST' }),
  performance: () => req<any>('/portfolio/performance'),
  setMode: (mode: string) =>
    req<any>('/portfolio/mode', { method: 'POST', body: JSON.stringify({ mode }) }),
  watchlist: () => req<{ tickers: string[] }>('/watchlist'),
  addWatch: (ticker: string) =>
    req<{ tickers: string[] }>('/watchlist', {
      method: 'POST',
      body: JSON.stringify({ ticker }),
    }),
  removeWatch: (ticker: string) =>
    req<{ tickers: string[] }>(`/watchlist/${ticker}`, { method: 'DELETE' }),
  setWatch: (tickers: string[]) =>
    req<{ tickers: string[] }>('/watchlist', {
      method: 'PUT',
      body: JSON.stringify({ tickers }),
    }),
  registerPush: (token: string) =>
    req('/notify/register', {
      method: 'POST',
      body: JSON.stringify({ token, platform: 'expo' }),
    }),
  learningStats: () => req<any>('/learning/stats'),
  paperTrade: (body: {
    ticker: string;
    shares: number;
    entry?: number;
    strategy_id?: string;
    confirm?: boolean;
  }) =>
    req<any>('/portfolio/orders', {
      method: 'POST',
      body: JSON.stringify({
        ticker: body.ticker,
        shares: body.shares,
        entry: body.entry,
        strategy_id: body.strategy_id,
        source: 'copilot_ui',
        human_approved: !!body.confirm,
      }),
      timeoutMs: 60_000,
    }),
  tradesImport: (format: 'csv' | 'json', content: string, dry_run = false) =>
    req<any>('/trades/import', {
      method: 'POST',
      body: JSON.stringify({ format, content, dry_run }),
      timeoutMs: SCAN_TIMEOUT_MS,
    }),
  tradesImportAlpaca: (dry_run = false, limit = 100) =>
    req<any>('/trades/import/alpaca', {
      method: 'POST',
      body: JSON.stringify({ dry_run, limit }),
      timeoutMs: SCAN_TIMEOUT_MS,
    }),
  tradesExternal: (limit = 50) => req<any>(`/trades/external?limit=${limit}`),
  tradesLearningStats: () => req<any>('/trades/learning-stats'),
  learningHistory: () => req<{ adjustments: any[] }>('/learning/history'),
  learningRun: () =>
    req<{ ran?: boolean; reason?: string; adjustments?: any[] }>('/learning/run', {
      method: 'POST',
      timeoutMs: SCAN_TIMEOUT_MS,
    }),
  learningReset: (wipe_journal = false) =>
    req<any>('/learning/reset', {
      method: 'POST',
      body: JSON.stringify({ wipe_journal, wipe_history: true, wipe_historical: false }),
    }),
  historicalTrain: (years = 20) =>
    req<any>('/learning/historical-train', {
      method: 'POST',
      body: JSON.stringify({ years }),
      timeoutMs: LONG_TIMEOUT_MS,
    }),
  historicalBaseline: () => req<any>('/learning/historical-baseline'),
  brokerStatus: () => req<any>('/broker/status'),
  brokerKill: () => req<any>('/broker/kill', { method: 'POST' }),
  regime: () => req<any>('/regime'),
  session: () => req<any>('/session'),
  news: (opts?: { eod?: boolean; limit?: number }) => {
    const q = new URLSearchParams();
    if (opts?.limit != null) q.set('limit', String(opts.limit));
    if (opts?.eod) q.set('eod', '1');
    const qs = q.toString();
    return req<any>(`/news${qs ? `?${qs}` : ''}`);
  },
  newsImpact: () => req<{ impact: any[] }>('/news/impact'),
  newsEod: () => req<any>('/news/eod'),
  newsTicker: (t: string) => req<any>(`/news/${t}`),
  currency: () => req<any>('/currency'),
  currencyPair: (pair: string) => req<any>(`/currency/${encodeURIComponent(pair)}`),
  copilot: (
    message: string,
    history: { role: string; content: string }[] = [],
    signal?: AbortSignal,
  ) =>
    req<{
      reply: string;
      intent?: string;
      source?: string;
      disclaimer?: string;
      tools_used?: string[];
      memory_updated?: boolean;
      sources?: string[];
      strategy_plan?: {
        ok?: boolean;
        active?: string[];
        regime_label?: string;
        mode?: string;
        weights?: Record<string, number>;
      };
    }>('/copilot', {
      method: 'POST',
      body: JSON.stringify({ message, history }),
      timeoutMs: 60_000,
      signal,
    }),
  dataSourceStatus: () => req<any>('/data-source/status'),
  setDataSource: (realtime_sip_enabled: boolean) =>
    req<any>('/data-source', {
      method: 'PUT',
      body: JSON.stringify({ realtime_sip_enabled }),
    }),
  dataSourceEvents: () => req<{ events: any[] }>('/data-source/events'),
  resetDataSourceFallback: () => req<any>('/data-source/reset-fallback', { method: 'POST' }),
  ownerStatus: () => req<any>('/owner/status'),
  ownerFiles: () => req<{ data_dir: string; files: { name: string; bytes: number }[] }>('/owner/files'),
  ownerExport: (name: string) => req<{ name: string; file: string; content: any }>(`/owner/export/${name}`),
  ownerImport: (name: string, content: any) =>
    req<{ ok: boolean }>(`/owner/import/${name}`, {
      method: 'PUT',
      body: JSON.stringify({ name, content }),
    }),
  autoStatus: () => req<any>('/auto/status'),
  strategies: () => req<any>('/strategies'),
  strategy: (id: string) => req<any>(`/strategies/${encodeURIComponent(id)}`),
  strategiesScoreboard: () => req<any>('/strategies/scoreboard'),
  crashMode: (refresh = false) =>
    req<any>(`/crash-mode${refresh ? '?refresh=1' : ''}`),
  auditDecisions: (limit = 40) =>
    req<{ count: number; decisions: any[]; path?: string }>(`/audit/decisions?limit=${limit}`),
  firewallStatus: () => req<any>('/firewall/status'),
  putAuto: (body: Record<string, any>) =>
    req<any>('/auto', { method: 'PUT', body: JSON.stringify(body) }),
  autoTradeRun: () =>
    req<any>('/auto/trade/run', { method: 'POST', timeoutMs: SCAN_TIMEOUT_MS }),
  autoLearnRun: () =>
    req<any>('/auto/learn/run', { method: 'POST', timeoutMs: SCAN_TIMEOUT_MS }),
  circuitBreaker: () => req<any>('/circuit-breaker'),
  circuitFalseTrip: (note = '') =>
    req<any>('/circuit-breaker/false-trip', { method: 'POST', body: JSON.stringify({ note }) }),
  circuitMissedBad: (note = '') =>
    req<any>('/circuit-breaker/missed-bad', { method: 'POST', body: JSON.stringify({ note }) }),
  circuitResume: (note = '') =>
    req<any>('/circuit-breaker/resume', { method: 'POST', body: JSON.stringify({ note }) }),
  learningReplay: (days = 5) =>
    req<any>('/learning/replay', {
      method: 'POST',
      body: JSON.stringify({ days }),
      timeoutMs: LONG_TIMEOUT_MS,
    }),
  positionFeedback: (id: string, rating?: string | null, note?: string) =>
    req<any>(`/portfolio/feedback/${id}`, {
      method: 'POST',
      body: JSON.stringify({ rating, note }),
    }),
  journalFeedback: (id: string, rating?: string | null, note?: string) =>
    req<any>(`/learning/feedback/${id}`, {
      method: 'POST',
      body: JSON.stringify({ rating, note }),
    }),

  strategiesPacks: () => req<{ packs: any[]; note?: string }>('/strategies/packs'),
  applyStrategyPack: (id: string) =>
    req<any>(`/strategies/packs/${encodeURIComponent(id)}/apply`, { method: 'POST' }),
  paperReport: (format: 'json' | 'csv' = 'json') =>
    req<any>(`/paper/report?format=${format}`, { timeoutMs: SCAN_TIMEOUT_MS }),
  scoreboardExport: (format: 'json' | 'csv' = 'json') =>
    req<any>(`/strategies/scoreboard/export?format=${format}`, { timeoutMs: SCAN_TIMEOUT_MS }),
  scanQuick: (extra: string[] = []) =>
    req<any>(`/scan/quick${extra.length ? `?extra=${encodeURIComponent(extra.join(','))}` : ''}`, {
      method: 'POST',
      timeoutMs: SCAN_TIMEOUT_MS,
    }),
  scanStatus: () => req<any>('/scan/status'),
  marketsCoverage: () => req<any>('/markets/coverage'),
  syncSnapshot: () => req<any>('/sync/snapshot'),
  previewStrategyPack: (id: string) =>
    req<any>(`/strategies/packs/${encodeURIComponent(id)}/preview`),
  optionsSummary: (ticker: string) =>
    req<any>(`/options/${encodeURIComponent(ticker)}`),
  optionsIdeas: (limit = 30) => req<any>(`/options/ideas?limit=${limit}`),
  logOptionsIdea: (body: {
    ticker: string; thesis: string; side?: string; expiry?: string; strike?: number; tags?: string[];
  }) =>
    req<any>('/options/ideas', { method: 'POST', body: JSON.stringify(body) }),
  paperLeaderboard: (limit = 20) =>
    req<any>(`/paper/leaderboard?limit=${limit}`),
  intradayHeat: (force = false) =>
    req<any>(`/scan/intraday-heat${force ? '?force=1' : ''}`, { timeoutMs: SCAN_TIMEOUT_MS }),
  syncTicks: (symbols: string[] = []) =>
    req<any>(
      `/sync/ticks${symbols.length ? `?symbols=${encodeURIComponent(symbols.join(','))}` : ''}`,
    ),
  brokersStatus: () => req<any>('/brokers/status'),
  testAlpacaBroker: (paper = true) =>
    req<any>(`/brokers/alpaca/test?paper=${paper ? 1 : 0}`, { method: 'POST' }),
  quotes: (symbols: string[] = []) =>
    req<any>(`/quotes${symbols.length ? `?symbols=${encodeURIComponent(symbols.join(','))}` : ''}`),
  edgeStatus: () => req<any>('/edge/status'),
  edgeWhy: () => req<any>('/edge/why'),
  edgeGaps: () => req<any>('/edge/gaps'),
  edgeImprovements: () => req<any>('/edge/improvements'),
  overnightResearch: (limit = 8) => req<any>(`/edge/overnight?limit=${limit}`),
  edgeCritique: () => req<any>('/edge/critique'),
  edgeCritiqueRun: () => req<any>('/edge/critique/run', { method: 'POST' }),
  overnightIngest: () => req<any>('/edge/overnight/ingest', { method: 'POST' }),
  alerts: (limit = 30) => req<any>(`/alerts?limit=${limit}`),
  evaluateAlerts: (force = false) =>
    req<any>(`/alerts/evaluate?force=${force ? 1 : 0}`, { method: 'POST' }),
  paperOptions: () => req<any>('/options/paper'),
  openPaperOption: (body: {
    ticker: string; side: 'call' | 'put'; contracts?: number; thesis?: string;
    strike?: number; expiry?: string;
  }) =>
    req<any>('/options/paper', { method: 'POST', body: JSON.stringify(body) }),
  closePaperOption: (id: string, reason = 'manual') =>
    req<any>(`/options/paper/close/${encodeURIComponent(id)}?reason=${encodeURIComponent(reason)}`, {
      method: 'POST',
    }),

  bars: (symbol: string, interval = '1d', limit = 120) =>
    req<any>(`/bars/${encodeURIComponent(symbol)}?interval=${encodeURIComponent(interval)}&limit=${limit}`),
  tape: (symbol: string, limit = 40) =>
    req<any>(`/tape/${encodeURIComponent(symbol)}?limit=${limit}`),
  ladder: (symbol: string, levels = 8) =>
    req<any>(`/ladder/${encodeURIComponent(symbol)}?levels=${levels}`),
  scanCustom: (body: Record<string, unknown>) =>
    req<any>('/scan/custom', { method: 'POST', body: JSON.stringify(body), timeoutMs: SCAN_TIMEOUT_MS }),
  economicCalendar: (days = 21, refresh = false) =>
    req<any>(`/calendar/economic?days=${days}&refresh=${refresh ? 1 : 0}`),
  optionsChain: (ticker: string, expiry = '') =>
    req<any>(`/options/${encodeURIComponent(ticker)}/chain${expiry ? `?expiry=${encodeURIComponent(expiry)}` : ''}`),
  proOrder: (body: {
    ticker: string; shares: number; order_type: string;
    entry?: number; stop?: number; take_profit?: number;
    trigger_price?: number; limit_price?: number; strategy_id?: string; human_approved?: boolean;
  }) =>
    req<any>('/portfolio/orders/pro', { method: 'POST', body: JSON.stringify(body) }),
  workingOrders: () => req<any>('/portfolio/orders/working'),
  manageWorkingOrders: () =>
    req<any>('/portfolio/orders/working/manage', { method: 'POST' }),
  cancelWorkingOrder: (id: string) =>
    req<any>(`/portfolio/orders/working/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  layoutPro: () => req<any>('/layout/pro'),

  deskCommand: (command: string, enrich = true) =>
    req<any>('/desk/command', { method: 'POST', body: JSON.stringify({ command, enrich }) }),
  deskCommandHelp: () => req<any>('/desk/command/help'),
  deskLayout: (preset = 'classic') =>
    req<any>(`/desk/layout?preset=${encodeURIComponent(preset)}`),
  deskMonitor: () => req<any>('/desk/monitor'),
  deskCrossAsset: () => req<any>('/desk/cross-asset'),
  deskBrief: (symbol: string) =>
    req<any>(`/desk/brief?symbol=${encodeURIComponent(symbol)}`),
  deskEveBrief: (symbol = '') =>
    req<any>(`/desk/eve-brief${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''}`),
  portfolioAnalytics: () => req<any>('/portfolio/analytics'),
  watchlistColumns: () => req<any>('/watchlist/columns'),
  setWatchlistColumns: (columns: string[]) =>
    req<any>('/watchlist/columns', { method: 'PUT', body: JSON.stringify({ columns }) }),

};


