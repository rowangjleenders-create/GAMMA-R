import React, { memo, useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Alert, TextInput, TouchableOpacity, Pressable,
} from 'react-native';
import { api } from '../api/client';
import { colors, space } from '../theme/tokens';
import { Card, PrimaryButton, SectionLabel, Title, Muted, Badge } from '../components/ui';
import { EmptyView } from '../components/StatusViews';
import { CandleChart } from '../components/CandleChart';
import { TapePanel } from '../components/TapePanel';
import { LadderPanel } from '../components/LadderPanel';

function fmtNum(n: unknown, digits = 2): string {
  const v = Number(n);
  return Number.isFinite(v) ? v.toFixed(digits) : '—';
}

function fmtPct(n: unknown, digits = 2): string {
  const v = Number(n);
  return Number.isFinite(v) ? `${(v * 100).toFixed(digits)}%` : '—';
}

const Row = memo(function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.row}>
      <Text style={styles.label}>{label}</Text>
      <Text style={styles.value}>{value}</Text>
    </View>
  );
});

export function SignalDetailScreen({ route }: any) {
  const signal = route.params?.signal;
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [lastOrderId, setLastOrderId] = useState<string | null>(null);
  const [optionsInfo, setOptionsInfo] = useState<any | null>(null);
  const [chain, setChain] = useState<any | null>(null);
  const [barInterval, setBarInterval] = useState('1d');
  const [bars, setBars] = useState<any[]>([]);
  const [tape, setTape] = useState<any | null>(null);
  const [ladder, setLadder] = useState<any | null>(null);

  const loadPro = useCallback(async (iv: string) => {
    const t = signal?.ticker;
    if (!t) return;
    try {
      const [b, tp, ld, o, ch] = await Promise.all([
        api.bars(t, iv, 80).catch(() => null),
        api.tape(t, 30).catch(() => null),
        api.ladder(t, 8).catch(() => null),
        api.optionsSummary(t).catch(() => null),
        api.optionsChain(t).catch(() => null),
      ]);
      if (b?.bars) setBars(b.bars);
      setTape(tp);
      setLadder(ld);
      setOptionsInfo(o);
      setChain(ch);
    } catch {
      /* ignore */
    }
  }, [signal?.ticker]);

  useEffect(() => {
    loadPro(barInterval);
    const id = globalThis.setInterval(() => {
      api.ladder(signal?.ticker, 8).then(setLadder).catch(() => {});
      api.tape(signal?.ticker, 30).then(setTape).catch(() => {});
    }, 4000);
    return () => clearInterval(id);
  }, [signal?.ticker, barInterval, loadPro]);

  if (!signal) {
    return (
      <View style={styles.container}>
        <EmptyView title="No signal" hint="Go back to Scan and open a row." />
      </View>
    );
  }

  const sendFeedback = async (rating: 'like' | 'dislike') => {
    if (!lastOrderId) {
      Alert.alert('Feedback', 'Place a paper order first (or open a closed trade from Portfolio).');
      return;
    }
    try {
      await api.positionFeedback(lastOrderId, rating, note);
      Alert.alert('Saved', `${rating} note attached to ${lastOrderId}`);
    } catch (e: any) {
      Alert.alert('Feedback failed', e.message);
    }
  };

  const executePaper = async () => {
    setBusy(true);
    try {
      const res = await api.order({
        ticker: signal.ticker,
        shares: signal.shares,
        entry: signal.entry,
        stop: signal.stop,
        take_profit: signal.take_profit,
        source: signal.source,
        forward_probability: signal.forward_probability,
        ensemble_votes: signal.ensemble_votes,
        confidence: signal.confidence,
        strategy_id: signal.strategy_id || 'momentum',
      });
      const fill = res as any;
      if (fill.id) setLastOrderId(String(fill.id));
      const fw = fill.firewall?.reason ? `\nFirewall: ${fill.firewall.reason}` : '';
      Alert.alert(
        'Paper fill',
        `${fill.ticker} x${fill.shares} @ ${fill.entry}\nstrategy=${fill.strategy_id || signal.strategy_id || 'momentum'}${fw}\n${fill.fill_note || ''}`,
      );
    } catch (e: any) {
      const msg = e.message || String(e);
      Alert.alert(msg.toLowerCase().includes('firewall') ? 'Firewall denied' : 'Order failed', msg);
    } finally {
      setBusy(false);
    }
  };

  const paperBracket = async () => {
    setBusy(true);
    try {
      const r = await api.proOrder({
        ticker: signal.ticker,
        shares: Number(signal.shares) || 1,
        order_type: 'bracket',
        entry: signal.entry,
        stop: signal.stop,
        take_profit: signal.take_profit,
        strategy_id: signal.strategy_id || 'momentum',
        human_approved: true,
      });
      if (r?.id) setLastOrderId(String(r.id));
      Alert.alert(r?.ok === false ? 'Bracket failed' : 'Paper bracket', JSON.stringify(r).slice(0, 320));
    } catch (e: any) {
      Alert.alert('Bracket failed', e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const paperFromChain = async (row: any) => {
    try {
      const r = await api.openPaperOption({
        ticker: signal.ticker,
        side: row.side === 'put' ? 'put' : 'call',
        contracts: 1,
        strike: row.strike,
        expiry: row.expiry || chain?.expiry,
        thesis: `Chain row ${row.side} ${row.strike} δ=${row.delta ?? '—'} (paper education)`,
      });
      Alert.alert(r.ok ? 'Paper option opened' : 'Failed', JSON.stringify(r).slice(0, 280));
    } catch (e: any) {
      Alert.alert('Paper option failed', e?.message || String(e));
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ paddingHorizontal: space.md, paddingTop: space.sm, paddingBottom: space.xxxl }}>
      <Pressable
        onLongPress={paperBracket}
        delayLongPress={450}
      >
        <View style={styles.titleRow}>
          <Title>{signal.ticker}</Title>
          <Badge label={signal.source === 'watchlist' ? 'WATCH' : 'SCAN'} tone={signal.source === 'watchlist' ? 'warn' : 'accent'} />
        </View>
        <Muted style={{ marginBottom: space.sm, marginTop: 4 }}>
          Long-press title for paper bracket · {signal.time_display || ''}
          {signal.after_hours ? ' · AFTER HOURS' : ''}
        </Muted>
      </Pressable>

      <Card>
        <SectionLabel style={{ marginTop: 0 }}>Pro chart</SectionLabel>
        <CandleChart
          bars={bars}
          interval={barInterval}
          onInterval={(iv) => {
            setBarInterval(iv);
            api.bars(signal.ticker, iv, 80).then((b) => setBars(b?.bars || [])).catch(() => {});
          }}
        />
      </Card>

      <Card>
        <SectionLabel style={{ marginTop: 0 }}>Ladder (NBBO)</SectionLabel>
        <LadderPanel
          rows={ladder?.rows || []}
          caption={ladder?.caption}
          bid={ladder?.bid}
          ask={ladder?.ask}
        />
      </Card>

      <Card>
        <SectionLabel style={{ marginTop: 0 }}>Time & Sales</SectionLabel>
        <TapePanel prints={tape?.prints || []} note={tape?.note} label={tape?.label} />
      </Card>

      <Card>
        <Row label="Strategy" value={signal.strategy_id || 'momentum'} />
        <Row label="Entry" value={`$${fmtNum(signal.entry)}`} />
        <Row label="Momentum" value={fmtPct(signal.momentum_pct)} />
        <Row label="Volume ratio" value={`x${fmtNum(signal.volume_ratio)}`} />
        <Row label="Stop-loss" value={`$${fmtNum(signal.stop)}`} />
        <Row label="Take-profit" value={`$${fmtNum(signal.take_profit)}`} />
        <Row label="Suggested shares" value={signal.shares != null ? String(signal.shares) : '—'} />
      </Card>

      {signal.forward_probability != null && (
        <Card>
          <SectionLabel style={{ marginTop: 0 }}>Forward estimate</SectionLabel>
          <Row label="P(continue)" value={fmtPct(signal.forward_probability, 1)} />
          <Row label="Confidence" value={fmtPct(signal.forward_confidence, 0)} />
          <Text style={styles.disclaimer}>Statistical estimate only — not a guarantee.</Text>
        </Card>
      )}

      {!!signal.ensemble_votes && (
        <Card>
          <SectionLabel style={{ marginTop: 0 }}>Ensemble votes</SectionLabel>
          {Object.entries(signal.ensemble_votes).map(([k, v]) => (
            <Row key={k} label={k} value={fmtPct(v, 1)} />
          ))}
        </Card>
      )}

      {signal.news_score_24h != null && (
        <Card>
          <SectionLabel style={{ marginTop: 0 }}>News sentiment</SectionLabel>
          <Row label="24h score" value={String(signal.news_score_24h)} />
          <Row label="Spike" value={signal.news_spike ? 'Yes' : 'No'} />
          {(signal.news_headlines || []).slice(0, 5).map((h: any, i: number) => (
            <Text key={i} style={styles.headline}>[{h.label}] {h.title}</Text>
          ))}
        </Card>
      )}

      {optionsInfo ? (
        <Card>
          <SectionLabel style={{ marginTop: 0 }}>Options research</SectionLabel>
          <Muted style={{ marginBottom: 8 }}>{optionsInfo.label || 'READ-ONLY'}</Muted>
          {optionsInfo.stub || !optionsInfo.available ? (
            <Text style={styles.disclaimer}>{optionsInfo.note || 'Enable options_read_only.'}</Text>
          ) : (
            <>
              <Row label="Nearest expiry" value={String(optionsInfo.nearest_expiry || '—')} />
              <Row label="ATM IV" value={optionsInfo.atm_iv != null ? fmtPct(optionsInfo.atm_iv, 1) : '—'} />
            </>
          )}
        </Card>
      ) : null}

      {chain?.rows?.length ? (
        <Card>
          <SectionLabel style={{ marginTop: 0 }}>Options chain + greeks</SectionLabel>
          <Muted style={{ marginBottom: 6 }}>
            {chain.label} · greeks={chain.greeks_source || '—'}
          </Muted>
          {chain.rows.slice(0, 16).map((r: any, i: number) => (
            <TouchableOpacity key={i} style={styles.chainRow} onPress={() => paperFromChain(r)}>
              <Text style={styles.chainTxt}>
                {r.side?.toUpperCase()} {fmtNum(r.strike)} · IV {r.iv != null ? fmtPct(r.iv, 0) : '—'} · δ {fmtNum(r.delta, 2)} γ {fmtNum(r.gamma, 4)}
              </Text>
              <Text style={styles.chainSub}>
                bid {fmtNum(r.bid)} / ask {fmtNum(r.ask)} · θ {fmtNum(r.theta, 3)} ν {fmtNum(r.vega, 3)} · tap = paper
              </Text>
            </TouchableOpacity>
          ))}
        </Card>
      ) : null}

      <PrimaryButton label={busy ? 'Working…' : 'Execute Paper Trade'} onPress={executePaper} disabled={busy} />
      <View style={{ height: 8 }} />
      <PrimaryButton label="Paper bracket (entry+stop+target)" onPress={paperBracket} disabled={busy} />
      <SectionLabel>Feedback (structured learning)</SectionLabel>
      <TextInput
        style={{ backgroundColor: colors.card, color: colors.text, padding: space.sm, borderRadius: 8, marginBottom: space.sm }}
        placeholder="Why like/dislike this setup?"
        placeholderTextColor={colors.muted}
        value={note}
        onChangeText={setNote}
        multiline
      />
      <View style={{ flexDirection: 'row', gap: 8, marginBottom: space.lg }}>
        <View style={{ flex: 1 }}>
          <PrimaryButton label="Like" onPress={() => sendFeedback('like')} />
        </View>
        <View style={{ flex: 1 }}>
          <PrimaryButton label="Dislike" onPress={() => sendFeedback('dislike')} tone="danger" />
        </View>
      </View>
      <View style={{ height: space.xxl }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  titleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  row: {
    flexDirection: 'row', justifyContent: 'space-between',
    paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.borderSubtle,
  },
  label: { color: colors.muted, fontSize: 14 },
  value: { color: colors.text, fontWeight: '600', fontSize: 14 },
  disclaimer: { color: colors.warn, marginTop: space.sm, fontSize: 12, lineHeight: 17 },
  headline: { color: colors.text, marginTop: 6, fontSize: 12 },
  chainRow: { paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.borderSubtle },
  chainTxt: { color: colors.text, fontSize: 12, fontWeight: '600' },
  chainSub: { color: colors.muted, fontSize: 11, marginTop: 2 },
});
