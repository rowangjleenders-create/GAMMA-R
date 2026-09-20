import React, { memo, useCallback, useRef, useState } from 'react';
import {
  View, Text, FlatList, StyleSheet, RefreshControl, Alert, TouchableOpacity,
} from 'react-native';
import { api } from '../api/client';
// feedback via api.positionFeedback
import { colors, space, radius, type } from '../theme/tokens';
import { useSilentRefresh } from '../hooks/useSilentRefresh';
import { EmptyView, ErrorBanner } from '../components/StatusViews';
import { SkeletonList } from '../components/Skeleton';
import { Card, Title, Muted, Badge, SectionLabel, PrimaryButton } from '../components/ui';
import { fixedGetItemLayout, POSITION_ROW_HEIGHT } from '../utils/listLayout';

function money(n: unknown, digits = 2): string {
  const v = Number(n);
  if (!Number.isFinite(v)) return '—';
  const sign = v < 0 ? '-' : '';
  return `${sign}$${Math.abs(v).toFixed(digits)}`;
}

function pct(n: unknown, digits = 2): string {
  const v = Number(n);
  if (!Number.isFinite(v)) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(digits)}%`;
}

const Stat = memo(function Stat({
  label, value, good,
}: { label: string; value: string; good?: boolean | null }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text
        style={[
          styles.statVal,
          good === true && { color: colors.good },
          good === false && { color: colors.bad },
        ]}
      >
        {value}
      </Text>
    </View>
  );
});

const PositionRow = memo(function PositionRow({
  item,
  onClose,
}: {
  item: any;
  onClose: (id: string) => void;
}) {
  const upnl = Number(item.unrealized_pnl ?? 0);
  const upct = Number(item.unrealized_pct ?? 0);
  const good = upnl > 0 ? true : upnl < 0 ? false : null;
  return (
    <View style={styles.rowWrap}>
      <Card style={styles.rowCard}>
        <View style={styles.rowTop}>
          <Text style={styles.ticker}>{item.ticker} × {item.shares}</Text>
          <Badge label="PAPER" tone="muted" />
        </View>
        <Text style={styles.meta}>
          Entry {money(item.entry)} · Last {money(item.last_price)}
          {item.market_value != null ? ` · MV ${money(item.market_value)}` : ''}
        </Text>
        <Text
          style={[
            styles.pnlLine,
            good === true && { color: colors.good },
            good === false && { color: colors.bad },
          ]}
        >
          Unrealized {money(upnl)} ({pct(upct)})
        </Text>
        <TouchableOpacity style={styles.closeBtn} onPress={() => onClose(item.id)} activeOpacity={0.85}>
          <Text style={styles.closeText}>Close</Text>
        </TouchableOpacity>
      </Card>
    </View>
  );
});

export function PortfolioScreen() {
  const [snap, setSnap] = useState<any>(null);
  const [analytics, setAnalytics] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState<any[]>([]);
  const hasData = useRef(false);

  const load = useCallback(async (opts: { silent?: boolean }, signal: AbortSignal) => {
    if (!opts.silent) {
      setRefreshing(true);
      setError(null);
    }
    try {
      const data = await api.portfolio();
      const wo = await api.workingOrders().catch(() => null);
      const an = await api.portfolioAnalytics().catch(() => null);
      if (signal.aborted) return;
      setSnap(data);
      if (wo?.orders) setWorking(wo.orders);
      if (an) setAnalytics(an);
      hasData.current = true;
      setError(null);
    } catch (e: any) {
      if (e?.name === 'AbortError' || signal.aborted) return;
      if (!opts.silent || !hasData.current) setError(e.message || String(e));
    } finally {
      if (!signal.aborted) {
        setRefreshing(false);
        setLoading(false);
      }
    }
  }, []);

  const { refresh } = useSilentRefresh(load, { intervalMs: 45_000 });

  const close = useCallback(async (id: string) => {
    setSnap((prev: any) => {
      if (!prev) return prev;
      const open = (prev.open_positions || []).filter((p: any) => p.id !== id);
      return { ...prev, open_positions: open };
    });
    try {
      await api.close(id);
      Alert.alert('Rate this trade?', 'Helps structured learning', [
        { text: 'Skip', style: 'cancel' },
        { text: 'Like', onPress: () => api.positionFeedback(id, 'like').catch(() => {}) },
        { text: 'Dislike', onPress: () => api.positionFeedback(id, 'dislike').catch(() => {}) },
      ]);
      await refresh();
    } catch (e: any) {
      Alert.alert('Close failed', e.message);
      refresh();
    }
  }, [refresh]);

  const renderItem = useCallback(
    ({ item }: { item: any }) => <PositionRow item={item} onClose={close} />,
    [close],
  );

  if (loading && !snap) {
    return (
      <View style={styles.container}>
        <SkeletonList rows={4} rowHeight={96} />
      </View>
    );
  }

  if (!snap) {
    return (
      <View style={styles.container}>
        {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}
        <EmptyView
          title="Paper portfolio unavailable"
          hint="Start the API (python -m momentum_bot) and set Settings → API server to your LAN URL."
          actionLabel="Retry"
          onAction={refresh}
        />
      </View>
    );
  }

  const positions = snap.open_positions || [];
  const totalPnl = Number(snap.total_pnl ?? (Number(snap.unrealized_pnl || 0) + Number(snap.realized_pnl || 0)));
  const ret = Number(snap.return_pct ?? 0);
  const equity = Number(snap.equity ?? 0);
  const starting = Number(snap.starting_cash ?? 0);
  const totalGood = totalPnl > 0 ? true : totalPnl < 0 ? false : null;

  return (
    <View style={styles.container}>
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}
      <Title>Paper Portfolio</Title>
      <Muted style={{ marginTop: 4, marginBottom: space.sm }}>
        Simulated fills only · mode {snap.mode === 'live' ? 'Live label' : 'Paper'}
        {snap.mode === 'live' ? ' (broker stays off unless LIVE_TRADING_ENABLED)' : ''}
      </Muted>
      {snap.live_note ? <Text style={styles.note}>{snap.live_note}</Text> : null}

      <Card style={styles.hero}>
        <View style={styles.heroTop}>
          <View style={{ flex: 1 }}>
            <Text style={styles.heroLabel}>Equity</Text>
            <Text style={styles.heroEquity}>{money(equity)}</Text>
            <Text style={styles.heroSub}>
              Start {money(starting)} · Cash {money(snap.cash)}
              {snap.market_value != null ? ` · Positions ${money(snap.market_value)}` : ''}
            </Text>
          </View>
          <Badge label="PAPER" tone="accent" />
        </View>
        <View style={styles.heroPnlRow}>
          <Text
            style={[
              styles.heroPnl,
              totalGood === true && { color: colors.good },
              totalGood === false && { color: colors.bad },
            ]}
          >
            Total P&L {money(totalPnl)}
          </Text>
          <Text
            style={[
              styles.heroRet,
              totalGood === true && { color: colors.good },
              totalGood === false && { color: colors.bad },
            ]}
          >
            {pct(ret)}
          </Text>
        </View>
        {(snap.closed_count != null || snap.total_fees_paid != null) && (
          <Text style={styles.heroSub}>
            Closed trades {snap.closed_count ?? 0}
            {snap.total_fees_paid != null ? ` · Fees paid ${money(snap.total_fees_paid)}` : ''}
          </Text>
        )}
      </Card>

      <View style={styles.grid}>
        <Stat
          label="Unrealized"
          value={money(snap.unrealized_pnl)}
          good={snap.unrealized_pnl > 0 ? true : snap.unrealized_pnl < 0 ? false : null}
        />
        <Stat
          label="Realized (net)"
          value={money(snap.realized_pnl)}
          good={snap.realized_pnl > 0 ? true : snap.realized_pnl < 0 ? false : null}
        />
        {snap.gross_realized_pnl != null && (
          <Stat label="Realized (gross)" value={money(snap.gross_realized_pnl)} />
        )}
        {snap.total_fees_paid != null && (
          <Stat label="Fees paid" value={money(snap.total_fees_paid)} />
        )}
      </View>

      <SectionLabel style={{ marginTop: space.sm }}>Analytics</SectionLabel>
      <Card style={{ marginBottom: space.sm }} accessibilityLabel="Portfolio analytics">
        {analytics?.ok ? (
          <>
            <Text style={styles.meta}>
              Invested {((analytics.exposure_vs_cash?.invested_pct || 0) * 100).toFixed(0)}%
              {' · '}Cash {((analytics.exposure_vs_cash?.cash_pct || 0) * 100).toFixed(0)}%
              {' · '}Win {((analytics.pnl_breakdown?.win_rate || 0) * 100).toFixed(0)}%
              {' · '}DD {((analytics.drawdown?.max_drawdown_pct || 0) * 100).toFixed(1)}%
            </Text>
            <Text style={[styles.meta, { marginTop: 4 }]}>
              P&L u/r {money(analytics.pnl_breakdown?.unrealized_pnl)} / {money(analytics.pnl_breakdown?.realized_pnl)}
              {analytics.pnl_breakdown?.closed_trades != null
                ? ` · Closed ${analytics.pnl_breakdown.closed_trades}`
                : ''}
            </Text>
            {(analytics.allocation_by_symbol || []).slice(0, 4).map((a: any) => (
              <Text key={a.ticker} style={[styles.meta, { marginTop: 2 }]}>
                {a.ticker} {((a.weight || 0) * 100).toFixed(0)}% · {a.sector || '?'} · {money(a.market_value)}
              </Text>
            ))}
            {!(analytics.allocation_by_symbol || []).length ? (
              <Muted style={{ marginTop: 4 }}>No open allocation — paper cash only</Muted>
            ) : null}
            <Text style={[styles.meta, { marginTop: 6, opacity: 0.85 }]}>
              PAPER · live locked · not Bloomberg PORT
            </Text>
          </>
        ) : (
          <Muted>Analytics unavailable — pull to refresh</Muted>
        )}
      </Card>

      <SectionLabel style={{ marginTop: space.sm }}>Paper pro orders</SectionLabel>
      <Card style={{ marginBottom: space.sm }}>
        <Muted style={{ marginBottom: 6 }}>Stop / TP / bracket / OCO — paper only through firewall</Muted>
        <PrimaryButton
          label="Manage working (fill triggers)"
          onPress={async () => {
            try {
              const r = await api.manageWorkingOrders();
              Alert.alert('Working orders', `actions=${r?.count ?? 0}`);
              const wo = await api.workingOrders();
              setWorking(wo?.orders || []);
              refresh();
            } catch (e: any) {
              Alert.alert('Manage failed', e?.message || String(e));
            }
          }}
        />
        {(working || []).slice(0, 8).map((o: any) => (
          <View key={o.id} style={{ paddingVertical: 6, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.borderSubtle }}>
            <Text style={{ color: colors.text, fontSize: 12, fontWeight: '600' }}>
              {o.order_type} {o.ticker} x{o.shares} @ {o.trigger_price}
            </Text>
            <TouchableOpacity onPress={async () => {
              await api.cancelWorkingOrder(o.id);
              const wo = await api.workingOrders();
              setWorking(wo?.orders || []);
            }}>
              <Text style={{ color: colors.bad, fontSize: 11, marginTop: 2 }}>Cancel</Text>
            </TouchableOpacity>
          </View>
        ))}
        {!working?.length ? <Muted>No working orders — use Signal detail long-press for paper bracket</Muted> : null}
      </Card>

      <SectionLabel style={{ marginTop: space.sm }}>Open positions</SectionLabel>
      <FlatList
        data={positions}
        keyExtractor={(item) => item.id}
        renderItem={renderItem}
        getItemLayout={fixedGetItemLayout(POSITION_ROW_HEIGHT)}
        initialNumToRender={8}
        maxToRenderPerBatch={8}
        windowSize={7}
        removeClippedSubviews
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />
        }
        ListEmptyComponent={
          error ? (
            <EmptyView
              compact
              title="Couldn’t refresh positions"
              hint="Pull to retry once the API is reachable. Equity above may be stale."
            />
          ) : (
            <EmptyView
              compact
              title="No open paper trades"
              hint="Go to Scan → open a signal → Execute Paper Trade. P&L and fees show up here after fills."
            />
          )
        }
        contentContainerStyle={
          positions.length ? { paddingBottom: space.xxl } : { flexGrow: 1, paddingBottom: space.xxl }
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bg,
    paddingHorizontal: space.md,
    paddingTop: space.sm,
  },
  hero: { marginBottom: space.sm },
  heroTop: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between' },
  heroLabel: { color: colors.muted, fontSize: 12, fontWeight: '600' },
  heroEquity: { ...type.hero, color: colors.text, marginTop: 2 },
  heroSub: { color: colors.muted, fontSize: 12, marginTop: 6, lineHeight: 17 },
  heroPnlRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    marginTop: space.md,
    paddingTop: space.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.borderSubtle,
  },
  heroPnl: { color: colors.text, fontWeight: '700', fontSize: 16 },
  heroRet: { color: colors.textSecondary, fontWeight: '700', fontSize: 15 },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.sm,
    marginBottom: space.xs,
  },
  stat: {
    width: '47%',
    backgroundColor: colors.card,
    padding: space.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  statLabel: { color: colors.muted, fontSize: 12 },
  statVal: { color: colors.text, fontWeight: '700', marginTop: 4, fontSize: 16 },
  rowWrap: { height: POSITION_ROW_HEIGHT },
  rowCard: { marginBottom: space.sm, minHeight: POSITION_ROW_HEIGHT - space.sm },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  ticker: { ...type.ticker, color: colors.text },
  meta: { ...type.meta, color: colors.muted, marginTop: 6 },
  pnlLine: { color: colors.textSecondary, fontWeight: '700', marginTop: 4, fontSize: 14 },
  note: { color: colors.warn, marginBottom: space.sm, fontSize: 12 },
  closeBtn: {
    marginTop: space.sm,
    alignSelf: 'flex-start',
    backgroundColor: colors.bad,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
    borderRadius: radius.sm,
  },
  closeText: { color: colors.white, fontWeight: '700', fontSize: 13 },
});
