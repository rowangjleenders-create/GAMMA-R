import React, { memo, useMemo } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import Svg, { Rect, Line, Polyline } from 'react-native-svg';
import { colors, space } from '../theme/tokens';

export type Bar = {
  t?: string;
  o?: number | null;
  h?: number | null;
  l?: number | null;
  c?: number | null;
  v?: number | null;
  vwap?: number | null;
};

const INTERVALS = ['1d', '1h', '15m', '5m'] as const;

/** SVG candle chart + volume + optional VWAP — no heavy chart lib. */
export const CandleChart = memo(function CandleChart({
  bars,
  interval,
  onInterval,
  width = 340,
  height = 180,
}: {
  bars: Bar[];
  interval: string;
  onInterval?: (iv: string) => void;
  width?: number;
  height?: number;
}) {
  const volH = 36;
  const chartH = height - volH;
  const pad = 4;

  const geometry = useMemo(() => {
    const clean = (bars || []).filter(
      (b) => b && Number.isFinite(Number(b.h)) && Number.isFinite(Number(b.l)) && Number.isFinite(Number(b.c)),
    );
    if (clean.length < 2) return null;
    const highs = clean.map((b) => Number(b.h));
    const lows = clean.map((b) => Number(b.l));
    const min = Math.min(...lows);
    const max = Math.max(...highs);
    const span = max - min || 1;
    const n = clean.length;
    const candleW = Math.max(2, (width - pad * 2) / n - 1);
    const y = (v: number) => pad + (1 - (v - min) / span) * (chartH - pad * 2);
    const candles = clean.map((b, i) => {
      const o = Number(b.o ?? b.c);
      const c = Number(b.c);
      const h = Number(b.h);
      const l = Number(b.l);
      const up = c >= o;
      const x = pad + i * ((width - pad * 2) / n) + 0.5;
      const bodyTop = y(Math.max(o, c));
      const bodyBot = y(Math.min(o, c));
      return {
        x,
        wickTop: y(h),
        wickBot: y(l),
        bodyTop,
        bodyH: Math.max(1, bodyBot - bodyTop),
        up,
        vwap: b.vwap != null && Number.isFinite(Number(b.vwap)) ? y(Number(b.vwap)) : null,
        vol: Number(b.v) || 0,
      };
    });
    const maxVol = Math.max(...candles.map((c) => c.vol), 1);
    const vwapPts = candles
      .map((c, i) => (c.vwap != null ? `${c.x + candleW / 2},${c.vwap}` : null))
      .filter(Boolean)
      .join(' ');
    return { candles, candleW, maxVol, vwapPts, min, max };
  }, [bars, width, chartH]);

  return (
    <View style={styles.wrap}>
      <View style={styles.ivRow}>
        {INTERVALS.map((iv) => (
          <TouchableOpacity
            key={iv}
            onPress={() => onInterval?.(iv)}
            style={[styles.ivChip, interval === iv && styles.ivChipOn]}
          >
            <Text style={[styles.ivText, interval === iv && styles.ivTextOn]}>{iv}</Text>
          </TouchableOpacity>
        ))}
      </View>
      {!geometry ? (
        <Text style={styles.empty}>No bars</Text>
      ) : (
        <Svg width={width} height={height}>
          {geometry.candles.map((c, i) => (
            <React.Fragment key={i}>
              <Line
                x1={c.x + geometry.candleW / 2}
                y1={c.wickTop}
                x2={c.x + geometry.candleW / 2}
                y2={c.wickBot}
                stroke={c.up ? colors.good : colors.bad}
                strokeWidth={1}
              />
              <Rect
                x={c.x}
                y={c.bodyTop}
                width={geometry.candleW}
                height={c.bodyH}
                fill={c.up ? colors.good : colors.bad}
              />
              <Rect
                x={c.x}
                y={chartH + (1 - c.vol / geometry.maxVol) * (volH - 2)}
                width={geometry.candleW}
                height={Math.max(1, (c.vol / geometry.maxVol) * (volH - 2))}
                fill={c.up ? colors.good : colors.bad}
                opacity={0.45}
              />
            </React.Fragment>
          ))}
          {geometry.vwapPts ? (
            <Polyline points={geometry.vwapPts} fill="none" stroke={colors.accent} strokeWidth={1.5} />
          ) : null}
        </Svg>
      )}
      <Text style={styles.caption}>
        Candles + volume{geometry?.vwapPts ? ' · VWAP' : ''} — not Level-2
      </Text>
    </View>
  );
});

const styles = StyleSheet.create({
  wrap: { marginVertical: space.sm },
  ivRow: { flexDirection: 'row', gap: 6, marginBottom: 8 },
  ivChip: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    backgroundColor: colors.card,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.borderSubtle,
  },
  ivChipOn: { backgroundColor: colors.accent },
  ivText: { color: colors.muted, fontSize: 12, fontWeight: '600' },
  ivTextOn: { color: '#0b0f14' },
  empty: { color: colors.muted, paddingVertical: 24, textAlign: 'center' },
  caption: { color: colors.muted, fontSize: 11, marginTop: 4 },
});
