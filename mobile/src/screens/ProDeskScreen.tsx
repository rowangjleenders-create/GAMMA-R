import React, { useCallback, useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  TouchableOpacity,
  useWindowDimensions,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { api } from '../api/client';
import { CommandBar, DeskRouteResult } from '../components/CommandBar';
import { LadderPanel } from '../components/LadderPanel';
import { CandleChart } from '../components/CandleChart';
import { colors, space, radius } from '../theme/tokens';
import { Card } from '../components/ui';

const PRESETS: { id: string; label: string; a11y: string }[] = [
  { id: 'classic', label: 'Classic', a11y: 'Classic desk layout' },
  { id: 'news-heavy', label: 'News-heavy', a11y: 'News-heavy layout' },
  { id: 'fx+equity', label: 'FX+Equity', a11y: 'FX and equity layout' },
  { id: 'eve-focus', label: 'E-ve focus', a11y: 'E-ve focus layout' },
];

function EmptyPanel({ title, hint }: { title: string; hint: string }) {
  return (
    <View style={styles.emptyBox} accessibilityRole="text">
      <Text style={styles.muted}>{title}</Text>
      <Text style={styles.cap}>{hint}</Text>
    </View>
  );
}

/** Mobile Pro Desk — 2x2 / scroll panels + sticky GO bar. */
export function ProDeskScreen() {
  const nav = useNavigation<any>();
  const { width } = useWindowDimensions();
  const half = Math.max(150, (width - space.md * 3) / 2);
  const [preset, setPreset] = useState<string>('classic');
  const [layout, setLayout] = useState<any>(null);
  const [monitor, setMonitor] = useState<any>(null);
  const [cross, setCross] = useState<any>(null);
  const [symbol, setSymbol] = useState('SPY');
  const [bars, setBars] = useState<any>(null);
  const [ladder, setLadder] = useState<any>(null);
  const [portfolio, setPortfolio] = useState<any>(null);
  const [analytics, setAnalytics] = useState<any>(null);
  const [brief, setBrief] = useState<any>(null);
  const [eveBrief, setEveBrief] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [lastToast, setLastToast] = useState<string | null>(null);

  const goTab = useCallback((tab: string, params?: any) => {
    const parent = nav.getParent?.();
    if (parent?.navigate) {
      parent.navigate(tab as never, params as never);
      return;
    }
    nav.navigate(tab as never, params as never);
  }, [nav]);

  const load = useCallback(async (p = preset, sym = symbol) => {
    setLoadError(null);
    try {
      const [lay, mon, xa, lad, br, port, b, an, eve] = await Promise.all([
        api.deskLayout(p),
        api.deskMonitor(),
        api.deskCrossAsset(),
        api.ladder(sym, 6).catch(() => null),
        api.deskBrief(sym).catch(() => null),
        api.portfolio().catch(() => null),
        api.bars(sym, '15m', 80).catch(() => null),
        api.portfolioAnalytics().catch(() => null),
        api.deskEveBrief(sym).catch(() => null),
      ]);
      setLayout(lay);
      setMonitor(mon);
      setCross(xa);
      setLadder(lad);
      setBrief(br);
      setPortfolio(port);
      setBars(b);
      setAnalytics(an);
      setEveBrief(eve);
    } catch (e: any) {
      setLoadError(String(e?.message || e).slice(0, 140));
    } finally {
      setLoading(false);
    }
  }, [preset, symbol]);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const onRoute = (res: DeskRouteResult) => {
    if (res?.toast) setLastToast(res.toast);
    if (res?.symbol) setSymbol(String(res.symbol).toUpperCase());
    const route = res?.route;
    if (!res?.ok && !route) {
      setLastToast(res?.hint || res?.error || 'Command not recognized — try HELP');
      return;
    }
    if (route === 'help') {
      setLastToast(res?.toast || 'GO help — AAPL · NEWS · CHART · TAPE · OPT · EVE · SCAN · MONITOR');
      return;
    }
    if (route === 'eve' || route === 'brief') {
      goTab('CoPilot');
      return;
    }
    if (route === 'scanner') {
      goTab('Scanner');
      return;
    }
    if (route === 'monitor') {
      load(preset, res.symbol || symbol);
      return;
    }
    if (
      res?.symbol &&
      (route === 'quote' || route === 'chart' || route === 'tape' || route === 'ladder' || route === 'news' || route === 'options')
    ) {
      nav.navigate('SignalDetail' as never, {
        ticker: String(res.symbol).toUpperCase(),
        deskRoute: route,
        interval: res.interval,
      } as never);
    }
  };

  const switchPreset = (id: string) => {
    setPreset(id);
    setLoading(true);
    load(id, symbol).finally(() => setLoading(false));
    setLastToast(`Layout · ${id}`);
  };

  const grid = layout?.layout?.mobile_grid || '2x2';
  const panels: any[] = layout?.layout?.panels || [];

  const renderPanel = (panel: any) => {
    const id = panel.id;
    const panelStyle = [styles.panel, grid === '2x2' ? { width: half } : null];

    if (id === 'quote_ladder' || id === 'ladder') {
      return (
        <Card key={id} style={panelStyle} accessibilityLabel={`${panel.title} for ${symbol}`}>
          <Text style={styles.ptitle}>{panel.title} · {symbol}</Text>
          {ladder ? (
            <LadderPanel
              rows={ladder.rows || ladder.levels || []}
              bid={ladder.bid ?? ladder.best_bid}
              ask={ladder.ask ?? ladder.best_ask}
              caption={ladder.caption}
            />
          ) : (
            <EmptyPanel title="No ladder data" hint="Pull to refresh · top-of-book only" />
          )}
          <Text style={styles.cap}>Top-of-book — not L2</Text>
        </Card>
      );
    }
    if (id === 'chart') {
      const candles = bars?.bars || bars?.candles || [];
      return (
        <Card key={id} style={panelStyle} accessibilityLabel={`Chart ${symbol}`}>
          <Text style={styles.ptitle}>{panel.title} · {symbol}</Text>
          {candles.length ? (
            <CandleChart bars={candles} interval={bars.interval || '15m'} height={140} />
          ) : (
            <EmptyPanel title="Chart empty" hint="Pull to refresh bars" />
          )}
        </Card>
      );
    }
    if (id === 'news_eod' || id === 'brief') {
      return (
        <Card key={id} style={panelStyle} accessibilityLabel={panel.title}>
          <Text style={styles.ptitle}>{panel.title}</Text>
          {loading && !brief ? (
            <EmptyPanel title="E-ve brief loading…" hint="Allowlisted web + local news" />
          ) : brief?.summary ? (
            <>
              <Text style={styles.body}>{(brief.summary || '').slice(0, 180)}</Text>
              {(brief?.sources || []).slice(0, 2).map((s: any, i: number) => (
                <Text key={i} style={styles.cap}>· {(s.title || s.url || '').slice(0, 50)}</Text>
              ))}
            </>
          ) : (
            <EmptyPanel title="No brief yet" hint="Pull to refresh · or GO BRIEF SPY" />
          )}
        </Card>
      );
    }
    if (id === 'calendar' || id === 'fx') {
      const movers = cross?.fx_movers || [];
      const cal = cross?.calendar_next || [];
      return (
        <Card key={id} style={panelStyle} accessibilityLabel={panel.title}>
          <Text style={styles.ptitle}>{panel.title}</Text>
          {movers.length || cal.length ? (
            <>
              {movers.slice(0, 3).map((m: any) => (
                <Text key={m.pair} style={styles.body}>
                  {m.pair} {(Number(m.change_pct) * 100).toFixed(2)}%
                </Text>
              ))}
              {cal.slice(0, 2).map((e: any) => (
                <Text key={e.id || e.title} style={styles.cap}>{(e.title || '').slice(0, 40)}</Text>
              ))}
            </>
          ) : (
            <EmptyPanel title="No FX / calendar rows" hint="Pull to refresh cross-asset" />
          )}
        </Card>
      );
    }
    if (id === 'portfolio') {
      const exp = analytics?.exposure_vs_cash;
      const dd = analytics?.drawdown;
      return (
        <Card key={id} style={panelStyle} accessibilityLabel="Portfolio analytics">
          <Text style={styles.ptitle}>{panel.title}</Text>
          {portfolio || analytics ? (
            <>
              <Text style={styles.body}>
                PAPER equity ${Number(portfolio?.equity ?? portfolio?.total_equity ?? exp?.equity ?? 0).toFixed(0)}
              </Text>
              {exp ? (
                <Text style={styles.body}>
                  Invested {((exp.invested_pct || 0) * 100).toFixed(0)}% · Cash {((exp.cash_pct || 0) * 100).toFixed(0)}%
                </Text>
              ) : null}
              {analytics?.pnl_breakdown ? (
                <Text style={styles.body}>
                  Win rate {((analytics.pnl_breakdown.win_rate || 0) * 100).toFixed(0)}% · DD {((dd?.max_drawdown_pct || 0) * 100).toFixed(1)}%
                </Text>
              ) : null}
              {(analytics?.allocation_by_symbol || []).slice(0, 3).map((a: any) => (
                <Text key={a.ticker} style={styles.cap}>
                  {a.ticker} {((a.weight || 0) * 100).toFixed(0)}% · {a.sector || '?'}
                </Text>
              ))}
              <Text style={styles.cap}>Live locked · not live audited</Text>
            </>
          ) : (
            <EmptyPanel title="Portfolio unavailable" hint="Pull to refresh analytics" />
          )}
        </Card>
      );
    }
    if (id === 'eve_mini' || id === 'monitor') {
      const lines = eveBrief?.lines || [];
      const strip = monitor?.strip || [];
      return (
        <Card key={id} style={panelStyle} accessibilityLabel={panel.title}>
          <Text style={styles.ptitle}>{panel.title}</Text>
          {id === 'eve_mini' && lines.length ? (
            lines.slice(0, 4).map((ln: string, i: number) => (
              <Text key={i} style={styles.body}>• {ln.slice(0, 90)}</Text>
            ))
          ) : strip.length ? (
            strip.slice(0, 4).map((it: any) => (
              <Text key={it.id} style={styles.body}>• {it.label}</Text>
            ))
          ) : (
            <EmptyPanel title="Monitor quiet" hint="Crash/heat/alerts clear" />
          )}
          <TouchableOpacity
            onPress={() => goTab('CoPilot')}
            accessibilityRole="button"
            accessibilityLabel="Ask E-ve"
          >
            <Text style={styles.link}>Ask E-ve →</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={async () => {
              try {
                const full = await api.deskEveBrief(symbol);
                setEveBrief(full);
                Alert.alert('E-ve', (full?.summary || 'Full desk brief ready').slice(0, 280));
              } catch (e: any) {
                Alert.alert('E-ve', String(e?.message || e).slice(0, 120));
              }
            }}
            accessibilityRole="button"
            accessibilityLabel="Full desk brief"
          >
            <Text style={styles.link}>Full desk brief</Text>
          </TouchableOpacity>
        </Card>
      );
    }
    return (
      <Card key={id} style={panelStyle}>
        <Text style={styles.ptitle}>{panel.title}</Text>
        <EmptyPanel title={`Panel ${id}`} hint="No wiring yet" />
      </Card>
    );
  };

  return (
    <View style={styles.container}>
      <CommandBar sticky onRoute={onRoute} />
      <ScrollView
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />
        }
        contentContainerStyle={{ paddingBottom: 40 }}
        accessibilityLabel="Pro Desk panels"
      >
        {/* Layout preset switcher */}
        <Text style={styles.sectionLabel}>Layout preset</Text>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.presets}
          accessibilityRole="tablist"
        >
          {PRESETS.map((p) => (
            <TouchableOpacity
              key={p.id}
              style={[styles.chip, preset === p.id && styles.chipOn]}
              onPress={() => switchPreset(p.id)}
              accessibilityRole="tab"
              accessibilityState={{ selected: preset === p.id }}
              accessibilityLabel={p.a11y}
            >
              <Text style={[styles.chipText, preset === p.id && styles.chipTextOn]}>{p.label}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>

        {lastToast ? (
          <Text style={styles.toast} accessibilityLiveRegion="polite">{lastToast}</Text>
        ) : null}
        {loadError ? (
          <Text style={styles.err}>{loadError} — pull to refresh</Text>
        ) : null}

        {/* Monitor strip */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.monStrip}>
          {(monitor?.strip || []).map((it: any) => (
            <TouchableOpacity
              key={it.id}
              style={[styles.monChip, it.severity === 'critical' && styles.monCrit, it.severity === 'warn' && styles.monWarn]}
              onPress={() => {
                if (it.symbol) {
                  setSymbol(it.symbol);
                  load(preset, it.symbol);
                }
              }}
              accessibilityRole="button"
              accessibilityLabel={it.label}
            >
              <Text style={styles.monText}>{it.label}</Text>
            </TouchableOpacity>
          ))}
          {!monitor?.strip?.length && !loading ? (
            <Text style={styles.muted}>Monitor clear — crash/heat/alerts quiet</Text>
          ) : null}
        </ScrollView>

        {loading && !panels.length ? (
          <View style={styles.loadingWrap}>
            <ActivityIndicator color={colors.accent} />
            <Text style={styles.muted}>Loading Pro Desk…</Text>
          </View>
        ) : (
          <View style={grid === '2x2' ? styles.grid : styles.scrollPanels}>
            {panels.length ? panels.map(renderPanel) : (
              <EmptyPanel title="No panels" hint="Layout preset returned empty" />
            )}
          </View>
        )}

        <Text style={styles.footer}>
          Pro Desk · keep working · ahead on AI desk vs terminals · behind on proprietary data · not BLP · not L2
        </Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  sectionLabel: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    paddingHorizontal: space.md,
    marginTop: space.sm,
  },
  presets: { paddingHorizontal: space.md, paddingVertical: space.sm, gap: space.sm },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingHorizontal: 12,
    paddingVertical: 6,
    marginRight: space.sm,
    backgroundColor: colors.card,
  },
  chipOn: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  chipText: { color: colors.muted, fontSize: 12, fontWeight: '600' },
  chipTextOn: { color: colors.accent },
  toast: { color: colors.accent, fontSize: 11, paddingHorizontal: space.md, marginBottom: 4 },
  err: { color: colors.bad, fontSize: 11, paddingHorizontal: space.md, marginBottom: 4 },
  monStrip: { paddingHorizontal: space.md, paddingBottom: space.sm, gap: space.sm },
  monChip: {
    backgroundColor: colors.cardAlt,
    borderRadius: radius.sm,
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginRight: space.sm,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  monCrit: { borderColor: colors.bad },
  monWarn: { borderColor: colors.warn },
  monText: { color: colors.text, fontSize: 11, fontWeight: '600' },
  grid: { flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: space.md, gap: space.sm },
  scrollPanels: { paddingHorizontal: space.md, gap: space.sm },
  panel: { marginBottom: space.sm, minHeight: 120 },
  ptitle: { color: colors.text, fontWeight: '700', fontSize: 12, marginBottom: 6 },
  body: { color: colors.textSecondary, fontSize: 12, marginBottom: 2 },
  muted: { color: colors.muted, fontSize: 11 },
  cap: { color: colors.muted, fontSize: 9, marginTop: 4 },
  link: { color: colors.accent, fontWeight: '700', fontSize: 12, marginTop: 8 },
  footer: { color: colors.muted, fontSize: 10, textAlign: 'center', margin: space.md },
  emptyBox: { paddingVertical: 8 },
  loadingWrap: { alignItems: 'center', padding: space.lg, gap: space.sm },
});
