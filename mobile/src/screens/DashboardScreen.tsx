import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, SectionList, RefreshControl, TouchableOpacity, Alert, ScrollView} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { api } from '../api/client';
import { Signal } from '../types';
import { colors, space, radius, type } from '../theme/tokens';
import { useNotifications } from '../hooks/useNotifications';
import { useSilentRefresh } from '../hooks/useSilentRefresh';
import { EmptyView, ErrorBanner } from '../components/StatusViews';
import { SkeletonList } from '../components/Skeleton';
import { Badge, Card } from '../components/ui';
import { CommandBar, DeskRouteResult } from '../components/CommandBar';
import { SIGNAL_ROW_HEIGHT, SIGNAL_SECTION_HEADER_HEIGHT } from '../utils/listLayout';

const SignalRow = memo(function SignalRow({
  item,
  onPress,
}: {
  item: Signal;
  onPress: (s: Signal) => void;
}) {
  const mom = (item.momentum_pct || 0) * 100;
  const isWatch = item.source === 'watchlist';
  return (
    <View style={styles.rowWrap}>
    <Card onPress={() => onPress(item)} style={styles.rowCard}>
      <View style={styles.rowTop}>
        <Text style={styles.ticker}>{item.ticker}</Text>
        <Badge label={isWatch ? 'WATCH' : 'SCAN'} tone={isWatch ? 'warn' : 'accent'} />
      </View>
      <Text style={styles.meta}>
        Mom {mom.toFixed(1)}% · Vol x{(item.volume_ratio || 0).toFixed(2)} · $
        {(item.entry || 0).toFixed(2)}
        {item.confidence != null ? ` · Conf ${((item.confidence || 0) * 100).toFixed(0)}%` : ''}
        {item.strategy_id ? ` · ${item.strategy_id}` : ''}
      </Text>
      {item.forward_probability != null && (
        <Text style={styles.fwd}>
          Forward {((item.forward_probability || 0) * 100).toFixed(0)}%
          {item.forward_confidence != null
            ? ` · conf ${((item.forward_confidence || 0) * 100).toFixed(0)}%`
            : ''}
          {item.forward_pass ? ' ✓' : ' ✗'}
          {item.forward_model ? ` · ${item.forward_model}` : ''}
        </Text>
      )}
      {item.regime ? <Text style={styles.meta}>Regime: {item.regime}</Text> : null}
      {(item as any).bid != null && (item as any).ask != null ? (
        <Text style={styles.meta}>
          Bid {Number((item as any).bid).toFixed(2)} / Ask {Number((item as any).ask).toFixed(2)}
          {(item as any).spread != null ? ` · spr ${Number((item as any).spread).toFixed(3)}` : ''}
        </Text>
      ) : null}
    </Card>
    </View>
  );
});

export function DashboardScreen() {
  const nav = useNavigation<any>();
  const [signals, setSignals] = useState<Signal[]>([]);
  const [newsImpact, setNewsImpact] = useState<any[]>([]);
  const [currencyPairs, setCurrencyPairs] = useState<any[]>([]);
  const [currencyNote, setCurrencyNote] = useState<string | null>(null);
  const [eodDigest, setEodDigest] = useState<any | null>(null);
  const [scanStatus, setScanStatus] = useState<any>(null);
  const [autoStatus, setAutoStatus] = useState<any>(null);
  const [scoreboardTeaser, setScoreboardTeaser] = useState<any | null>(null);
  const [dataMode, setDataMode] = useState<string | null>(null);
  const [quickBusy, setQuickBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [liveUpdating, setLiveUpdating] = useState(false);
  const [syncStale, setSyncStale] = useState(false);
  const [paperEquity, setPaperEquity] = useState<number | null>(null);
  const [pollSec, setPollSec] = useState(3);
  const [feedBadge, setFeedBadge] = useState<string>('Delayed');
  const [intradayHeat, setIntradayHeat] = useState<any | null>(null);
  const [leaderboardTeaser, setLeaderboardTeaser] = useState<any | null>(null);
  const [edgeCard, setEdgeCard] = useState<any | null>(null);
  const [monitorStrip, setMonitorStrip] = useState<any[]>([]);
  const [quoteMap, setQuoteMap] = useState<Record<string, any>>({});
  const [econEvents, setEconEvents] = useState<any[]>([]);
  const [proLayout, setProLayout] = useState(true);
  const hasDataRef = useRef(false);
  useNotifications();

  const load = useCallback(async (opts: { silent?: boolean }, signal: AbortSignal) => {
    if (!opts.silent) {
      setRefreshing(true);
      setError(null);
    }
    try {
      // Lightweight live-feeling sync on every focus/poll
      try {
        const snap = await api.syncSnapshot();
        if (!signal.aborted && snap) {
          setLiveUpdating(!!snap.live_updating);
          setSyncStale(!!snap.stale);
          if (snap.poll_recommended_sec) setPollSec(Number(snap.poll_recommended_sec) || 3);
          if (snap.paper?.equity != null) setPaperEquity(Number(snap.paper.equity));
          if (snap.scan) {
            setScanStatus((prev: any) => ({ ...(prev || {}), ...(snap.scan || {}), data_label: snap.data_source?.data_label }));
          }
          if (snap.data_source?.data_label) setDataMode(snap.data_source.data_label);
          if (snap.data_source?.feed_badge) setFeedBadge(String(snap.data_source.feed_badge));
          else if (snap.data_source?.data_label) {
            const lab = String(snap.data_source.data_label);
            if (/\bSIP\b/i.test(lab)) setFeedBadge('SIP');
            else if (/\bIEX\b/i.test(lab)) setFeedBadge('IEX');
            else setFeedBadge('Delayed');
          }
          if (snap.crash_mode) {
            setAutoStatus((prev: any) => ({
              ...(prev || {}),
              crash_mode: { ...(prev?.crash_mode || {}), ...snap.crash_mode },
            }));
          }
        }
      } catch { /* optional lightweight path */ }
      const data = opts.silent ? await api.signals() : await api.scan();
      if (signal.aborted) return;
      setSignals(data.signals || []);
      hasDataRef.current = true;
      try {
        const a = await api.autoStatus();
        if (!signal.aborted) setAutoStatus(a);
      } catch { /* optional */ }
      try {
        const sb = await api.strategiesScoreboard();
        if (!signal.aborted) setScoreboardTeaser(sb);
      } catch { /* optional */ }
      try {
        const heat = await api.intradayHeat(false);
        if (!signal.aborted) setIntradayHeat(heat);
      } catch { /* optional */ }
      try {
        const lb = await api.paperLeaderboard(8);
        if (!signal.aborted) setLeaderboardTeaser(lb);
      } catch { /* optional */ }
      try {
        const why = await api.edgeWhy();
        if (!signal.aborted) setEdgeCard(why);
      } catch { /* optional */ }
      try {
        const mon = await api.deskMonitor();
        if (!signal.aborted) setMonitorStrip(mon?.strip || []);
      } catch { /* optional */ }
      try {
        const qx = await api.quotes([]);
        if (!signal.aborted) {
          if (qx?.feed_badge) setFeedBadge(String(qx.feed_badge));
          const map: Record<string, any> = {};
          for (const q of qx?.quotes || []) {
            if (q?.ticker) map[String(q.ticker).toUpperCase()] = q;
          }
          setQuoteMap(map);
        }
      } catch { /* optional */ }
      try {
        const st = await api.scanStatus();
        if (!signal.aborted) {
          setScanStatus((prev: any) => ({ ...(prev || {}), ...(st || {}) }));
          setDataMode(st?.data_label || st?.data_mode || null);
        }
      } catch { /* optional */ }
      if ((data as any).scan_status) {
        setScanStatus((data as any).scan_status);
      }
      if ((data as any).news_impact) {
        setNewsImpact((data as any).news_impact);
      } else if (!opts.silent) {
        try {
          const n = await api.newsImpact();
          if (!signal.aborted) setNewsImpact(n.impact || []);
        } catch { /* optional */ }
      }
      // Currency panel + EOD digest (informational; tolerate failures)
      try {
        if ((data as any).currency_top_movers?.length && opts.silent) {
          // keep existing pairs on silent refresh unless we re-fetch
        }
        const fx = await api.currency();
        if (!signal.aborted && fx?.enabled !== false) {
          setCurrencyPairs(fx.pairs || []);
          setCurrencyNote(fx.session_note || null);
        }
      } catch { /* optional */ }
      try {
        const eod = await api.newsEod();
        if (!signal.aborted) setEodDigest(eod);
      } catch { /* optional */ }
      setError(null);
    } catch (e: any) {
      if (e?.name === 'AbortError' || signal.aborted) return;
      if (!opts.silent || !hasDataRef.current) setError(e.message || String(e));
    } finally {
      if (!signal.aborted) {
        setRefreshing(false);
        setLoading(false);
      }
    }
  }, []);

  const intervalMs = Math.max(2000, Math.min(30_000, (pollSec || 3) * 1000));

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [cal, lay] = await Promise.all([
          api.economicCalendar(14).catch(() => null),
          api.layoutPro().catch(() => null),
        ]);
        if (cancelled) return;
        if (cal?.events) setEconEvents(cal.events);
        if (lay?.pro_layout != null) setProLayout(!!lay.pro_layout);
      } catch { /* ignore */ }
    })();
    return () => { cancelled = true; };
  }, []);

  const { refresh } = useSilentRefresh(load, { intervalMs });

  const onQuickScan = useCallback(async () => {
    setQuickBusy(true);
    setError(null);
    try {
      const res = await api.scanQuick();
      setSignals(res.signals || []);
      if (res.scan_status) setScanStatus(res.scan_status);
      const sip = res.data_source?.realtime_sip_enabled || res.scan_status?.data_mode === 'realtime_sip';
      if (sip) setDataMode('REALTIME (SIP)');
      else if (res.scan_status?.data_label) setDataMode(res.scan_status.data_label);
      else setDataMode('DELAYED (free)');
      hasDataRef.current = true;
    } catch (e: any) {
      const msg = e?.message || String(e);
      setError(/reach|connect|Network/i.test(msg) ? `${msg} — check Settings → API base URL.` : msg);
    } finally {
      setQuickBusy(false);
    }
  }, []);

  const onOpen = useCallback((s: Signal) => {
    nav.navigate('SignalDetail', { ticker: s.ticker, signal: s });
  }, [nav]);

  const sections = useMemo(() => {
    const watch = signals.filter((s) => s.source === 'watchlist');
    const market = signals.filter((s) => s.source !== 'watchlist');
    const out: { title: string; data: Signal[] }[] = [];
    if (watch.length) out.push({ title: 'Watchlist Signals', data: watch });
    if (market.length) out.push({ title: 'Market Scan (top 10%)', data: market });
    return out;
  }, [signals]);

    const scanFreshness = useMemo(() => {
    if (!scanStatus) return null;
    const age = scanStatus.cache_age_sec;
    const n = scanStatus.cached_count ?? signals.length;
    if (age == null && !scanStatus.has_cache) return 'No scan cache yet — pull to scan or tap Quick scan';
    if (age == null) return `${n} signal${n === 1 ? '' : 's'} cached`;
    const ageLabel =
      age < 60 ? `${Math.round(age)}s ago`
      : age < 3600 ? `${Math.round(age / 60)}m ago`
      : `${(age / 3600).toFixed(1)}h ago`;
    const fresh = scanStatus.cache_fresh ? 'fresh' : 'STALE';
    const warn = scanStatus.stale_warning ? ' · refresh recommended' : '';
    const kind = scanStatus.scan_kind ? ` · ${scanStatus.scan_kind}` : '';
    const mode = dataMode ? ` · ${dataMode}` : (scanStatus.data_mode ? ` · ${scanStatus.data_mode}` : '');
    const last = scanStatus.last_scan_at ? ` · at ${String(scanStatus.last_scan_at).slice(11, 19)}Z` : '';
    return `Last scan ${ageLabel}${last} · ${n} signal${n === 1 ? '' : 's'} · ${fresh}${kind}${mode}${warn}`;
  }, [scanStatus, signals.length, dataMode]);

  const renderItem = useCallback(
    ({ item }: { item: Signal }) => <SignalRow item={{ ...item, ...(quoteMap[(item.ticker || '').toUpperCase()] || {}) } as any} onPress={onOpen} />,
    [onOpen],
  );

  const renderSectionHeader = useCallback(
    ({ section }: { section: { title: string } }) => (
      <View style={styles.sectionHeader}>
        <Text style={styles.section}>{section.title}</Text>
      </View>
    ),
    [],
  );

  const getItemLayout = useCallback(
    (_data: any, index: number) => {
      // Approximate flat index layout (headers + rows). Good enough for jump/scroll perf.
      let offset = 0;
      let flat = 0;
      for (const sec of sections) {
        if (flat === index) {
          return { length: SIGNAL_SECTION_HEADER_HEIGHT, offset, index };
        }
        offset += SIGNAL_SECTION_HEADER_HEIGHT;
        flat += 1;
        for (let i = 0; i < sec.data.length; i++) {
          if (flat === index) {
            return { length: SIGNAL_ROW_HEIGHT, offset, index };
          }
          offset += SIGNAL_ROW_HEIGHT;
          flat += 1;
        }
      }
      return { length: SIGNAL_ROW_HEIGHT, offset: offset, index };
    },
    [sections],
  );

  const onDeskRoute = useCallback((res: DeskRouteResult) => {
    const route = res?.route;
    if (route === 'eve' || route === 'brief') {
      nav.navigate('CoPilot' as never);
      return;
    }
    if (route === 'scanner') {
      nav.navigate('Scanner' as never);
      return;
    }
    if (route === 'monitor' || route === 'help') {
      nav.navigate('ProDesk' as never);
      return;
    }
    if (
      res?.symbol &&
      (route === 'quote' || route === 'chart' || route === 'tape' || route === 'ladder' || route === 'news' || route === 'options')
    ) {
      nav.navigate('SignalDetail' as never, {
        ticker: res.symbol,
        deskRoute: route,
        interval: res.interval,
      } as never);
      return;
    }
    if (res?.symbol) {
      nav.navigate('SignalDetail' as never, { ticker: res.symbol } as never);
    }
  }, [nav]);

  if (loading && !signals.length) {
    return (
      <View style={styles.container}>
        <SkeletonList rows={6} rowHeight={88} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {proLayout ? <CommandBar sticky onRoute={onDeskRoute} /> : null}
      {monitorStrip.length ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ maxHeight: 36, marginBottom: 4 }} contentContainerStyle={{ paddingHorizontal: space.md, gap: 8 }}>
          {monitorStrip.map((it) => (
            <TouchableOpacity key={it.id} onPress={() => nav.navigate('ProDesk' as never)}>
              <View style={{ backgroundColor: colors.cardAlt, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4, borderWidth: 1, borderColor: it.severity === 'critical' ? colors.bad : it.severity === 'warn' ? colors.warn : colors.borderSubtle }}>
                <Text style={{ color: colors.text, fontSize: 10, fontWeight: '600' }}>{it.label}</Text>
              </View>
            </TouchableOpacity>
          ))}
        </ScrollView>
      ) : null}
      <View style={styles.badgeRow}>
        <Badge
          label={
            feedBadge === 'NBBO' ? 'NBBO'
              : feedBadge === 'SIP' ? 'SIP'
              : feedBadge === 'IEX' ? 'IEX'
              : 'Delayed'
          }
          tone={feedBadge === 'SIP' || feedBadge === 'IEX' || feedBadge === 'NBBO' ? 'accent' : 'warn'}
        />
        <Text style={[styles.freshness, { marginBottom: 0, marginLeft: 8, flex: 1 }, syncStale ? { color: colors.warn || colors.bad } : null]}>
          {liveUpdating ? '● live updating' : '○ stale'}
          {paperEquity != null ? ` · PAPER $${paperEquity.toFixed(0)}` : ''}
          {` · poll ${pollSec}s`}
          {' · not L2'}
        </Text>
        <TouchableOpacity onPress={() => nav.navigate('ProDesk' as never)} hitSlop={8}>
          <Text style={{ color: colors.accent, fontWeight: '700', fontSize: 11 }}>Pro Desk</Text>
        </TouchableOpacity>
      </View>

      {econEvents.length ? (
        <Card style={{ marginHorizontal: space.md, marginBottom: space.sm, paddingVertical: proLayout ? 8 : 12 }}>
          <Text style={{ color: colors.text, fontWeight: '700', fontSize: proLayout ? 12 : 14 }}>Econ calendar</Text>
          {econEvents.slice(0, proLayout ? 3 : 5).map((e: any) => (
            <Text key={e.id || e.title} style={{ color: colors.muted, fontSize: 11, marginTop: 2 }}>
              {(e.when || '').slice(5, 16)} · {e.impact?.toUpperCase()} · {e.title}
            </Text>
          ))}
          <Text style={{ color: colors.muted, fontSize: 10, marginTop: 4 }}>Curated rail — approx UTC</Text>
        </Card>
      ) : null}

      {autoStatus ? (
        <Card style={{ marginHorizontal: space.md, marginBottom: space.sm, paddingVertical: proLayout ? 8 : 12 }}>
          <Text style={{ color: colors.text, fontWeight: '600', fontSize: proLayout ? 13 : 14 }}>
            Auto {autoStatus.loops_started ? 'ON' : 'OFF'}
            {autoStatus.trading_halted ? ' · CIRCUIT HALTED' : ''}
          </Text>
          <Text style={{ color: colors.muted, fontSize: 12, marginTop: 4 }}>
            learn={String(autoStatus.auto_learn_enabled)} trade={String(autoStatus.auto_trade_enabled)}
            {autoStatus.last_scan_at ? ` · scan ${autoStatus.last_scan_at}` : ''}
            {autoStatus.circuit_breaker?.reason ? ` · ${autoStatus.circuit_breaker.reason}` : ''}
          </Text>
          {(autoStatus.strategies_last_cycle?.fired?.length || autoStatus.router_mode) ? (
            <Text style={{ color: colors.muted, fontSize: 12, marginTop: 4 }}>
              Strategies ({autoStatus.router_mode || 'auto'}):{' '}
              {(autoStatus.strategies_last_cycle?.fired || []).join(', ') || 'waiting for cycle'}
              {autoStatus.router?.regime_label ? ` · regime ${autoStatus.router.regime_label}` : ''}
            </Text>
          ) : null}
          {autoStatus.crash_mode?.active ? (
            <Text style={{ color: colors.bad, fontSize: 13, marginTop: 6, fontWeight: '700' }}>
              Crash mode: ON until {autoStatus.crash_mode.until || '—'}
              {autoStatus.crash_mode.reason ? ` — ${String(autoStatus.crash_mode.reason).slice(0, 90)}` : ''}
            </Text>
          ) : autoStatus.crash_mode?.enabled === false ? (
            <Text style={{ color: colors.muted, fontSize: 12, marginTop: 4 }}>Crash mode: disabled</Text>
          ) : (
            <Text style={{ color: colors.muted, fontSize: 12, marginTop: 4 }}>
              Crash mode: OFF (armed)
            </Text>
          )}
        </Card>
      ) : null}
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}
      {scanFreshness ? (
        <Text style={styles.freshness} accessibilityRole="text">
          {scanFreshness}
        </Text>
      ) : null}

      <View style={styles.ctaRow}>
        <TouchableOpacity
          style={[styles.ctaBtn, styles.ctaPrimary]}
          onPress={refresh}
          disabled={refreshing || quickBusy}
          accessibilityRole="button"
          accessibilityLabel="Full market scan"
        >
          <Text style={styles.ctaText}>{refreshing ? 'Scanning…' : 'Scan'}</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.ctaBtn, styles.ctaSecondary]}
          onPress={onQuickScan}
          disabled={refreshing || quickBusy}
          accessibilityRole="button"
          accessibilityLabel="Quick scan watchlist"
        >
          <Text style={styles.ctaTextSecondary}>{quickBusy ? 'Quick…' : 'Quick scan'}</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.ctaBtn, styles.ctaSecondary]}
          onPress={() => nav.navigate('Scanner')}
          accessibilityRole="button"
          accessibilityLabel="Pro scanner builder"
        >
          <Text style={styles.ctaTextSecondary}>Pro scanner</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.ctaBtn, styles.ctaSecondary]}
          onPress={() => nav.navigate('CoPilot' as never)}
          accessibilityRole="button"
          accessibilityLabel="Open E-ve"
        >
          <Text style={styles.ctaTextSecondary}>E-ve</Text>
        </TouchableOpacity>
      </View>
      {intradayHeat?.hits?.length ? (
        <Card style={{ marginHorizontal: space.md, marginBottom: space.sm }}>
          <Text style={{ color: colors.text, fontWeight: '700' }}>Intraday heat</Text>
          <Text style={{ color: colors.muted, fontSize: 11, marginTop: 2 }}>
            {(intradayHeat.label || 'Bar anomalies').slice(0, 80)} · {intradayHeat.interval || '?'} · not L2
          </Text>
          {(intradayHeat.hits || []).slice(0, 6).map((h: any) => (
            <Text key={h.ticker} style={{ color: colors.textSecondary, fontSize: 12, marginTop: 4 }}>
              {h.ticker} · heat {h.heat}
              {h.volume_ratio != null ? ` · vol x${Number(h.volume_ratio).toFixed(1)}` : ''}
              {h.change_pct != null ? ` · ${(Number(h.change_pct) * 100).toFixed(2)}%` : ''}
              {h.flags?.length ? ` · ${(h.flags || []).slice(0, 2).join(',')}` : ''}
            </Text>
          ))}
        </Card>
      ) : intradayHeat && !intradayHeat.hits?.length ? (
        <Card style={{ marginHorizontal: space.md, marginBottom: space.sm }}>
          <Text style={{ color: colors.text, fontWeight: '700' }}>Intraday heat</Text>
          <Text style={{ color: colors.muted, fontSize: 12, marginTop: 4 }}>
            No volume/range/velocity hits right now ({intradayHeat.interval || '5m'}). Pull to refresh.
          </Text>
        </Card>
      ) : null}

      <TouchableOpacity onPress={() => nav.navigate('Settings' as never)} activeOpacity={0.85}>
        <Card style={{ marginHorizontal: space.md, marginBottom: space.sm }}>
          <Text style={{ color: colors.text, fontWeight: '700' }}>Strategy packs</Text>
          <Text style={{ color: colors.muted, fontSize: 12, marginTop: 4 }}>
            One-tap packs in Settings — paper-first, live stays locked.
          </Text>
        </Card>
      </TouchableOpacity>

      {leaderboardTeaser ? (
        <TouchableOpacity onPress={() => nav.navigate('Learning' as never)} activeOpacity={0.85}>
          <Card style={{ marginHorizontal: space.md, marginBottom: space.sm }}>
            <Text style={{ color: colors.text, fontWeight: '700' }}>PAPER leaderboard</Text>
            <Text style={{ color: colors.muted, fontSize: 12, marginTop: 4 }}>
              {leaderboardTeaser.watermark || 'PAPER — not live audited'}
            </Text>
            <Text style={{ color: colors.muted, fontSize: 12, marginTop: 4 }}>
              {((leaderboardTeaser.ranks || []).slice(0, 3).map((r: any) =>
                `${r.name || r.strategy_id} n=${r.sample_size || 0}`
              ).join(' · ')) || 'Close paper trades to rank strategies'}
            </Text>
          </Card>
        </TouchableOpacity>
      ) : null}

      {scoreboardTeaser ? (
        <TouchableOpacity onPress={() => nav.navigate('Learning' as never)} activeOpacity={0.85}>
          <Card style={{ marginHorizontal: space.md, marginBottom: space.sm }}>
            <Text style={{ color: colors.text, fontWeight: '700' }}>PAPER scoreboard</Text>
            <Text style={{ color: colors.muted, fontSize: 12, marginTop: 4 }}>
              {(scoreboardTeaser.label || 'Rolling paper journal').slice(0, 90)}
              {' · '}not live audited
            </Text>
            <Text style={{ color: colors.muted, fontSize: 12, marginTop: 4 }}>
              {((scoreboardTeaser.strategies || []).slice(0, 3).map((s: any) =>
                `${(s.status || '').toUpperCase()} ${s.name || s.strategy_id}`
              ).join(' · ')) || 'No scored strategies yet — close paper trades'}
            </Text>
          </Card>
        </TouchableOpacity>
      ) : null}
      
      {edgeCard ? (
        <Card style={{ marginHorizontal: space.md, marginBottom: space.sm }}>
          <Text style={{ color: colors.accent, fontWeight: '700', marginBottom: 4 }}>
            {edgeCard.badge ? `${edgeCard.badge} · ` : ''}{edgeCard.title || 'Beat retail bots'}
          </Text>
          <Text style={{ color: colors.muted, fontSize: 12, marginBottom: 6 }}>{edgeCard.tagline || edgeCard.subtitle}</Text>
          {(edgeCard.bullets || []).slice(0, 4).map((b: any) => (
            <Text key={b.id || b.title} style={{ color: colors.text, fontSize: 12, marginBottom: 3 }}>
              • {b.title}
            </Text>
          ))}
          {edgeCard.vs_bots_one_liner ? (
            <Text style={{ color: colors.muted, fontSize: 11, marginTop: 4 }}>{edgeCard.vs_bots_one_liner}</Text>
          ) : null}
          <Text style={{ color: colors.warn, fontSize: 10, marginTop: 4 }}>Ahead on AI desk · behind on BLP data · Not L2 · PAPER first</Text>
        </Card>
      ) : null}

      <SectionList
        sections={sections}
        keyExtractor={(item) => `${item.ticker}-${item.source}`}
        renderItem={renderItem}
        renderSectionHeader={renderSectionHeader}
        stickySectionHeadersEnabled={false}
        initialNumToRender={8}
        maxToRenderPerBatch={8}
        windowSize={7}
        removeClippedSubviews
        ListHeaderComponent={
          <View>
            {currencyPairs?.filter((p) => p?.ok).length ? (
              <View style={styles.impactBox}>
                <Text style={styles.section}>Currency</Text>
                {currencyNote ? (
                  <Text style={[styles.meta, { marginBottom: 4 }]}>{currencyNote}</Text>
                ) : null}
                {currencyPairs.filter((p) => p?.ok).slice(0, 9).map((p) => {
                  const ch = Number(p.change_pct);
                  const up = Number.isFinite(ch) && ch >= 0;
                  const chLabel = Number.isFinite(ch) ? `${(ch * 100).toFixed(2)}%` : '—';
                  const last =
                    p.last == null ? '—'
                    : Number(p.last) < 10 ? Number(p.last).toFixed(4)
                    : Number(p.last).toFixed(2);
                  return (
                    <View key={p.pair} style={styles.fxRow}>
                      <Text style={styles.fxPair}>{p.pair}</Text>
                      <Text style={styles.fxLast}>{last}</Text>
                      <Text style={{ color: up ? colors.good : colors.bad, fontWeight: '600', fontSize: 13, minWidth: 64, textAlign: 'right' }}>
                        {Number.isFinite(ch) && ch > 0 ? '+' : ''}{chLabel}
                      </Text>
                    </View>
                  );
                })}
              </View>
            ) : null}
            {eodDigest?.top_headlines?.length ? (
              <View style={styles.impactBox}>
                <Text style={styles.section}>End of day news</Text>
                <Text style={[styles.meta, { marginBottom: 6 }]}>
                  {(eodDigest.tilt || 'neutral').toUpperCase()} tilt
                  {eodDigest.tilt_score != null ? ` · ${(Number(eodDigest.tilt_score) * 100).toFixed(0)}` : ''}
                  {eodDigest.headline_count != null ? ` · ${eodDigest.headline_count} headlines` : ''}
                </Text>
                {(eodDigest.top_headlines || []).slice(0, 5).map((h: any, idx: number) => {
                  const lab = (h.label || 'neutral') as string;
                  const tone = lab === 'positive' ? colors.good : lab === 'negative' ? colors.bad : colors.muted;
                  return (
                    <Text key={`${idx}-${h.title}`} style={[styles.meta, { color: colors.textSecondary }]} numberOfLines={2}>
                      <Text style={{ color: tone, fontWeight: '700' }}>· </Text>
                      {h.title}
                    </Text>
                  );
                })}
              </View>
            ) : null}
            {newsImpact?.length ? (
              <View style={styles.impactBox}>
                <Text style={styles.section}>News impact (sectors)</Text>
                {newsImpact.slice(0, 4).map((s) => {
                  const move = Number(s.movement);
                  const moveS = Number.isFinite(move) ? `${(move * 100).toFixed(1)}%` : '—';
                  return (
                    <Text key={s.sector} style={styles.meta}>
                      {s.sector}: move {moveS} (24h {s.score_24h ?? '—'})
                    </Text>
                  );
                })}
              </View>
            ) : null}
          </View>
        }
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />
        }
        ListEmptyComponent={
          error ? (
            <EmptyView
              compact
              title="Couldn’t load a scan"
              hint="Fix the connection above, then retry. API URL lives in Settings."
            />
          ) : (
            <EmptyView
              compact
              title="No signals yet"
              hint="Pull down to scan the market (S&P 500 ∪ Nasdaq-100)."
              actionLabel="Scan now"
              onAction={refresh}
            />
          )
        }
        contentContainerStyle={signals.length ? { paddingBottom: space.xxl } : { flexGrow: 1 }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg, paddingHorizontal: space.md, paddingTop: space.sm },
  rowWrap: { height: SIGNAL_ROW_HEIGHT },
  rowCard: { marginBottom: space.sm, minHeight: SIGNAL_ROW_HEIGHT - space.sm - 2 },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  ticker: { ...type.ticker, color: colors.text },
  meta: { ...type.meta, color: colors.muted, marginTop: 6 },
  fwd: { color: colors.good, marginTop: 4, fontWeight: '600', fontSize: 13 },
  section: {
    ...type.section,
    color: colors.muted,
    textTransform: 'uppercase',
    backgroundColor: colors.bg,
  },
  sectionHeader: {
    height: SIGNAL_SECTION_HEADER_HEIGHT,
    justifyContent: 'center',
    backgroundColor: colors.bg,
  },
  impactBox: {
    backgroundColor: colors.card,
    padding: space.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    marginBottom: space.sm,
  },
  ctaRow: {
    flexDirection: 'row', gap: 8, marginHorizontal: space.md, marginBottom: space.sm,
  },
  ctaBtn: {
    flex: 1, paddingVertical: 10, borderRadius: radius.md, alignItems: 'center',
  },
  ctaPrimary: { backgroundColor: colors.accent },
  ctaSecondary: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border || '#333' },
  ctaText: { color: '#fff', fontWeight: '700', fontSize: 14 },
  ctaTextSecondary: { color: colors.text, fontWeight: '600', fontSize: 13 },
  freshness: {
    ...type.meta,
    color: colors.muted,
    marginBottom: space.sm,
  },
  fxRow: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    justifyContent: 'space-between' as const,
    marginTop: 6,
  },
  fxPair: { ...type.bodyStrong, color: colors.text, minWidth: 72 },
  fxLast: { ...type.mono, color: colors.textSecondary, flex: 1, textAlign: 'center' as const },
});
