import React, { useEffect, useRef, memo } from 'react';
import { Animated, StyleSheet, View, ViewStyle } from 'react-native';
import { colors, radius, space } from '../theme/tokens';

export const Skeleton = memo(function Skeleton({ height = 56, style }: { height?: number; style?: ViewStyle }) {
  const opacity = useRef(new Animated.Value(0.35)).current;
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.7, duration: 700, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 0.35, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [opacity]);
  return <Animated.View style={[styles.bone, { height, opacity }, style]} accessibilityRole="progressbar" />;
});

export const SkeletonList = memo(function SkeletonList({ rows = 5, rowHeight = 76 }: { rows?: number; rowHeight?: number }) {
  return (
    <View style={styles.list}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} height={rowHeight} />
      ))}
    </View>
  );
});

const styles = StyleSheet.create({
  bone: {
    backgroundColor: colors.cardAlt,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  list: { gap: space.sm + 2, paddingTop: space.xs },
});
