import React, { memo, useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, FlatList, TextInput, StyleSheet, TouchableOpacity, Alert, RefreshControl, ScrollView,
} from 'react-native';
import { api } from '../api/client';
import { colors, space, radius, type } from '../theme/tokens';
import { useSilentRefresh } from '../hooks/useSilentRefresh';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { EmptyView, ErrorBanner } from '../components/StatusViews';
import { SkeletonList } from '../components/Skeleton';
import { Card, Title, Muted, PrimaryButton } from '../components/ui';
import { fixedGetItemLayout, WATCHLIST_ROW_HEIGHT } from '../utils/listLayout';

const TickerRow = memo(function TickerRow({
  ticker,
  onRemove,
  quote,
  feedBadge,
}: {
  ticker: string;
  onRemove: (t: string) => void;
  quote?: any;
  feedBadge?: string;
}) {
  const bid = quote?.bid;
  const ask = quote?.ask;
  const spread = quote?.spread;
  return (
    <View style={styles.rowWrap}>
      <Card style={styles.rowCard}>
        <View style={styles.row}>
          <View style={{ flex: 1 }}>
            <Text style={styles.ticker}>{ticker}</Text>
            {bid != null && ask != null ? (
              <Text style={{ color: '#9aa', fontSize: 11, marginTop: 2 }}>
                {Number(bid).toFixed(2)} / {Number(ask).toFixed(2)}
                {spread != null ? ` · spr ${Number(spread).toFixed(3)}` : ''}
                {feedBadge ? ` · ${feedBadge}` : ''}
              </Text>
            ) : quote?.price != null ? (
              <Text style={{ color: '#9aa', fontSize: 11, marginTop: 2 }}>
                last {Number(quote.price).toFixed(2)} · {feedBadge || 'Delayed'}
              </Text>
            ) : null}
          </View>
          <TouchableOpacity onPress={() => onRemove(ticker)} hitSlop={10}>
            <Text style={styles.remove}>Remove</Text>
          </TouchableOpacity>
        </View>
      </Card>
    </View>
  );
});

function parseTickers(raw: string): string[] {
  return Array.from(
    new Set(
      raw
        .toUpperCase()
        .split(/[\s,;]+/)
        .map((t) => t.replace(/[^A-Z0-9.\-]/g, ''))
        .filter((t) => t.length > 0 && t.length <= 12),
    ),
  );
}

export function WatchlistScreen() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [columns, setColumns] = useState<string[]>(['last','bid','ask','spread','pct_chg','volume','signal_score','news_tilt']);
  const [input, setInput] = useState('');
  const debouncedInput = useDebouncedValue(input, 200);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasData = useRef(false);
  const [quoteMap, setQuoteMap] = useState<Record<string, any>>({});
  const [feedBadge, setFeedBadge] = useState('Delayed');
  const backoffRef = useRef(2000);

  useEffect(() => {
    let cancelled = false;
    let timer: any;
    const tick = async () => {
      try {
        const qx = await api.quotes(tickers);
        if (cancelled) return;
        if (qx?.feed_badge) setFeedBadge(String(qx.feed_badge));
        const map: Record<string, any> = {};
        for (const q of qx?.quotes || []) {
          if (q?.ticker) map[String(q.ticker).toUpperCase()] = q;
        }
        setQuoteMap(map);
        backoffRef.current = qx?.feed_badge && qx.feed_badge !== 'Delayed' ? 2000 : 5000;
      } catch {
        backoffRef.current = Math.min(30000, (backoffRef.current || 2000) * 2);
      }
      if (!cancelled) timer = setTimeout(tick, backoffRef.current);
    };
    tick();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [tickers]);


  const load = useCallback(async (opts: { silent?: boolean }, signal: AbortSignal) => {
    if (!opts.silent) {
      setRefreshing(true);
      setError(null);
    }
    try {
      const r = await api.watchlist();
      if (signal.aborted) return;
      setTickers(r.tickers || []);
      try {
        const cols = await api.watchlistColumns();
        if (!signal.aborted && cols?.columns?.length) setColumns(cols.columns);
      } catch { /* optional */ }
      hasData.current = true;
      setError(null);
    } catch (e: any) {
      if (e?.name === 'AbortError' || signal.aborted) return;
      if (!opts.silent || !hasData.current) setError(e.message || String(e));
    } finally {
      if (!signal.aborted) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  const { refresh } = useSilentRefresh(load, { intervalMs: 120_000 });

  const add = useCallback(async () => {
    const parsed = parseTickers(debouncedInput || input);
    if (!parsed.length) return;
    const prev = tickers;
    const next = Array.from(new Set([...tickers, ...parsed]));
    setTickers(next);
    setInput('');
    try {
      if (parsed.length === 1) {
        const r = await api.addWatch(parsed[0]);
        setTickers(r.tickers || []);
      } else {
        const r = await api.setWatch(next);
        setTickers(r.tickers || []);
      }
      setError(null);
    } catch (e: any) {
      setTickers(prev);
      Alert.alert('Add failed', e.message);
    }
  }, [debouncedInput, input, tickers]);

  const remove = useCallback(async (t: string) => {
    setTickers((prev) => prev.filter((x) => x !== t));
    try {
      const r = await api.removeWatch(t);
      setTickers(r.tickers || []);
    } catch (e: any) {
      Alert.alert('Remove failed', e.message);
      refresh();
    }
  }, [refresh]);

  const renderItem = useCallback(
    ({ item }: { item: string }) => <TickerRow ticker={item} onRemove={remove} quote={quoteMap[item.toUpperCase()]} feedBadge={feedBadge} />,
    [remove],
  );

  if (loading && !tickers.length && !error) {
    return (
      <View style={styles.container}>
        <SkeletonList rows={5} rowHeight={56} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}
      <Title>Manual Watchlist</Title>
      <Muted style={{ marginVertical: space.sm }}>
        Scored every scan even outside the top 10% cut. Paste several tickers separated by space or comma.
      </Muted>
      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          placeholder="AAPL, MSFT, NVDA"
          placeholderTextColor={colors.muted}
          autoCapitalize="characters"
          autoCorrect={false}
          value={input}
          onChangeText={setInput}
          onSubmitEditing={add}
          returnKeyType="done"
        />
        <PrimaryButton label="Add" onPress={add} style={styles.addBtn} />
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ maxHeight: 32, marginBottom: 6 }}>
        <Text style={{ color: colors.muted, fontSize: 10, marginRight: 8, alignSelf: 'center' }}>Columns:</Text>
        {columns.map((c) => (
          <View key={c} style={{ backgroundColor: colors.cardAlt, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4, marginRight: 6 }}>
            <Text style={{ color: colors.textSecondary, fontSize: 10 }}>{c}</Text>
          </View>
        ))}
      </ScrollView>
      <FlatList
        data={tickers}
        keyExtractor={(t) => t}
        renderItem={renderItem}
        getItemLayout={fixedGetItemLayout(WATCHLIST_ROW_HEIGHT)}
        initialNumToRender={14}
        maxToRenderPerBatch={12}
        windowSize={7}
        removeClippedSubviews
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />
        }
        ListEmptyComponent={
          error ? (
            <EmptyView
              compact
              title="Couldn’t load watchlist"
              hint="Check Settings → API server, then retry."
            />
          ) : (
            <EmptyView
              compact
              title="No tickers yet"
              hint="Add symbols you want scored every scan — paste several separated by space or comma."
            />
          )
        }
        contentContainerStyle={tickers.length ? { paddingBottom: space.xxl } : { flexGrow: 1 }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg, paddingHorizontal: space.md, paddingTop: space.sm },
  inputRow: { flexDirection: 'row', gap: space.sm, marginBottom: space.md, alignItems: 'center' },
  input: {
    flex: 1,
    backgroundColor: colors.card,
    color: colors.text,
    padding: space.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  addBtn: { marginTop: 0, paddingHorizontal: 18, paddingVertical: 12 },
  rowWrap: { height: WATCHLIST_ROW_HEIGHT },
  rowCard: { marginBottom: space.sm, minHeight: WATCHLIST_ROW_HEIGHT - space.sm },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  ticker: { ...type.ticker, color: colors.text },
  remove: { color: colors.bad, fontWeight: '600' },
});
