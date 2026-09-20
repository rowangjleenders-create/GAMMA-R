import React, { memo } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, space } from '../theme/tokens';
import { Muted } from './ui';

export const TapePanel = memo(function TapePanel({
  prints,
  note,
  label,
}: {
  prints: Array<{ t?: string; price?: number | null; size?: number | null; approx?: boolean }>;
  note?: string;
  label?: string;
}) {
  return (
    <View style={styles.wrap}>
      <Muted style={{ marginBottom: 6 }}>{label || 'Time & Sales (tape lite)'}</Muted>
      {!prints?.length ? (
        <Text style={styles.empty}>{note || 'No prints — honest empty (not full tape).'}</Text>
      ) : (
        prints.slice(0, 24).map((p, i) => (
          <View key={i} style={styles.row}>
            <Text style={styles.time}>{(p.t || '').slice(11, 19) || '—'}</Text>
            <Text style={styles.px}>{p.price != null ? Number(p.price).toFixed(2) : '—'}</Text>
            <Text style={styles.sz}>{p.size != null ? String(p.size) : '—'}</Text>
            {p.approx ? <Text style={styles.approx}>≈</Text> : null}
          </View>
        ))
      )}
      <Text style={styles.cap}>Recent prints only — not full exchange Time & Sales</Text>
    </View>
  );
});

const styles = StyleSheet.create({
  wrap: { marginTop: space.xs },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 3,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.borderSubtle,
  },
  time: { color: colors.muted, fontSize: 11, width: 56 },
  px: { color: colors.text, fontSize: 12, fontWeight: '600', flex: 1, textAlign: 'right' },
  sz: { color: colors.muted, fontSize: 11, width: 56, textAlign: 'right' },
  approx: { color: colors.warn, fontSize: 10, marginLeft: 4 },
  empty: { color: colors.muted, fontSize: 12, paddingVertical: 8 },
  cap: { color: colors.muted, fontSize: 10, marginTop: 6 },
});
