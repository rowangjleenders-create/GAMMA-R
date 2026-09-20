import React, { memo, useMemo } from 'react';
import { View } from 'react-native';
import Svg, { Polyline } from 'react-native-svg';
import { colors } from '../theme/tokens';

/** Tiny SVG sparkline — no chart library required. */
export const Sparkline = memo(function Sparkline({
  points,
  width = 160,
  height = 36,
  color,
}: {
  points: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  const stroke = color || colors.accent;
  const poly = useMemo(() => {
    const vals = (points || []).map(Number).filter((n) => Number.isFinite(n));
    if (vals.length < 2) return '';
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = max - min || 1;
    const step = width / (vals.length - 1);
    return vals
      .map((v, i) => {
        const x = i * step;
        const y = height - ((v - min) / span) * (height - 4) - 2;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }, [points, width, height]);

  if (!poly) {
    return <View style={{ width, height }} />;
  }
  return (
    <Svg width={width} height={height}>
      <Polyline points={poly} fill="none" stroke={stroke} strokeWidth={2} />
    </Svg>
  );
});
