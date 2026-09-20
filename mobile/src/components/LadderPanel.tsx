import React, { memo } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, space } from '../theme/tokens';
import { Muted } from './ui';

type Row = {
  price?: number;
  side?: string | null;
  size?: number | null;
  top_of_book?: boolean;
  is_mid?: boolean;
  placeholder?: boolean;
};

export const LadderPanel = memo(function LadderPanel({
  rows,
  caption,
  bid,
  ask,
}: {
  rows: Row[];
  caption?: string;
  bid?: number | null;
  ask?: number | null;
}) {
  return (
    <View style={styles.wrap}>
      <Muted style={{ marginBottom: 4 }}>
        {caption || 'Top-of-book ladder — not full exchange depth.'}
      </Muted>
      <Text style={styles.nbbo}>
        Bid {bid != null ? Number(bid).toFixed(2) : '—'} / Ask {ask != null ? Number(ask).toFixed(2) : '—'}
      </Text>
      {(rows || []).map((r, i) => {
        const isAsk = r.side === 'ask';
        const isBid = r.side === 'bid';
        return (
          <View
            key={i}
            style={[
              styles.row,
              r.is_mid && styles.mid,
              r.top_of_book && styles.tob,
            ]}
          >
            <Text style={[styles.size, isBid && { color: colors.good }]}>
              {isBid && r.size != null ? String(r.size) : ''}
            </Text>
            <Text
              style={[
                styles.px,
                isAsk && { color: colors.bad },
                isBid && { color: colors.good },
                r.is_mid && { color: colors.accent },
              ]}
            >
              {r.price != null ? Number(r.price).toFixed(2) : '—'}
            </Text>
            <Text style={[styles.size, isAsk && { color: colors.bad }]}>
              {isAsk && r.size != null ? String(r.size) : ''}
            </Text>
          </View>
        );
      })}
      <Text style={styles.cap}>Only TOB rows have real size — placeholders are visual</Text>
    </View>
  );
});

const styles = StyleSheet.create({
  wrap: { marginTop: space.xs },
  nbbo: { color: colors.text, fontSize: 12, marginBottom: 6, fontWeight: '600' },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 2,
  },
  mid: { backgroundColor: 'rgba(88,166,255,0.08)' },
  tob: { backgroundColor: 'rgba(63,185,80,0.08)' },
  size: { width: 48, fontSize: 11, color: colors.muted, textAlign: 'center' },
  px: { flex: 1, textAlign: 'center', fontSize: 12, color: colors.muted, fontVariant: ['tabular-nums'] as any },
  cap: { color: colors.muted, fontSize: 10, marginTop: 6 },
});
