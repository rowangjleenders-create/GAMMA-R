import React, { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, Alert,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { api } from '../api/client';
import { colors, space } from '../theme/tokens';
import { Card, PrimaryButton, SectionLabel, Title, Muted, Badge } from '../components/ui';

export function ScannerScreen() {
  const nav = useNavigation<any>();
  const [minVolRatio, setMinVolRatio] = useState('1.2');
  const [minPct, setMinPct] = useState('0');
  const [region, setRegion] = useState('US');
  const [strategyId, setStrategyId] = useState('');
  const [newsTilt, setNewsTilt] = useState('any');
  const [priceMin, setPriceMin] = useState('');
  const [priceMax, setPriceMax] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any | null>(null);

  const run = useCallback(async () => {
    setBusy(true);
    try {
      const body: Record<string, unknown> = {
        min_volume_ratio: Number(minVolRatio) || undefined,
        min_pct_change: Number(minPct) || undefined,
        region: region || undefined,
        strategy_id: strategyId || undefined,
        news_tilt: newsTilt,
        refresh: true,
        limit: 40,
      };
      if (priceMin) body.price_min = Number(priceMin);
      if (priceMax) body.price_max = Number(priceMax);
      const r = await api.scanCustom(body);
      setResult(r);
    } catch (e: any) {
      Alert.alert('Custom scan failed', e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }, [minVolRatio, minPct, region, strategyId, newsTilt, priceMin, priceMax]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: space.md, paddingBottom: 48 }}>
      <Title>Pro scanner</Title>
      <Muted style={{ marginBottom: space.md }}>
        Builder filters on GAMMA-R signals — not Trade Ideas L2 heat.
      </Muted>

      <Card>
        <SectionLabel style={{ marginTop: 0 }}>Filters</SectionLabel>
        <Field label="Min volume ratio" value={minVolRatio} onChange={setMinVolRatio} />
        <Field label="Min % change (frac or %)" value={minPct} onChange={setMinPct} />
        <Field label="Region (US/UK/CA/JP/HK)" value={region} onChange={setRegion} />
        <Field label="Strategy id" value={strategyId} onChange={setStrategyId} placeholder="momentum / blank=any" />
        <Field label="News tilt" value={newsTilt} onChange={setNewsTilt} placeholder="any|bullish|bearish" />
        <Field label="Price min" value={priceMin} onChange={setPriceMin} />
        <Field label="Price max" value={priceMax} onChange={setPriceMax} />
        <PrimaryButton label={busy ? 'Scanning…' : 'Run custom scan'} onPress={run} disabled={busy} />
      </Card>

      {result ? (
        <Card>
          <View style={styles.head}>
            <SectionLabel style={{ marginTop: 0 }}>Results</SectionLabel>
            <Badge label={`${result.count || 0}`} tone="accent" />
          </View>
          <Muted style={{ marginBottom: 8 }}>{result.label}</Muted>
          {(result.signals || []).map((s: any) => (
            <TouchableOpacity
              key={s.ticker}
              style={styles.sig}
              onPress={() => nav.navigate('SignalDetail', { signal: s })}
            >
              <Text style={styles.ticker}>{s.ticker}</Text>
              <Text style={styles.meta}>
                mom {((s.momentum_pct || 0) * 100).toFixed(1)}% · vol x{(s.volume_ratio || 0).toFixed(2)} · $
                {(s.entry || 0).toFixed(2)}
                {s.strategy_id ? ` · ${s.strategy_id}` : ''}
              </Text>
            </TouchableOpacity>
          ))}
          {!result.signals?.length ? <Muted>No matches — loosen filters or run a full scan first.</Muted> : null}
        </Card>
      ) : null}
    </ScrollView>
  );
}

function Field({
  label, value, onChange, placeholder,
}: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <View style={{ marginBottom: 10 }}>
      <Text style={styles.flabel}>{label}</Text>
      <TextInput
        style={styles.input}
        value={value}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={colors.muted}
        autoCapitalize="none"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  flabel: { color: colors.muted, fontSize: 12, marginBottom: 4 },
  input: {
    backgroundColor: colors.bg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderSubtle,
    borderRadius: 8,
    color: colors.text,
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  sig: {
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.borderSubtle,
  },
  ticker: { color: colors.text, fontWeight: '700', fontSize: 15 },
  meta: { color: colors.muted, fontSize: 12, marginTop: 2 },
});
