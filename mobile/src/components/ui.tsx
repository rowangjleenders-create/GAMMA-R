import React, { memo } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Switch, ViewStyle, TextStyle, Pressable,
} from 'react-native';
import { colors, space, radius, type, shadow } from '../theme/tokens';

export const Screen = memo(function Screen({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[styles.screen, style]}>{children}</View>;
});

export const Card = memo(function Card({
  children, style, onPress,
}: { children: React.ReactNode; style?: ViewStyle; onPress?: () => void }) {
  if (onPress) {
    return (
      <Pressable onPress={onPress} style={({ pressed }) => [styles.card, shadow.card, pressed && styles.cardPressed, style]}>
        {children}
      </Pressable>
    );
  }
  return <View style={[styles.card, shadow.card, style]}>{children}</View>;
});

export const SectionLabel = memo(function SectionLabel({ children, style }: { children: React.ReactNode; style?: TextStyle }) {
  return <Text style={[styles.section, style]}>{children}</Text>;
});

export const Title = memo(function Title({ children, style }: { children: React.ReactNode; style?: TextStyle }) {
  return <Text style={[styles.title, style]}>{children}</Text>;
});

export const Muted = memo(function Muted({ children, style }: { children: React.ReactNode; style?: TextStyle }) {
  return <Text style={[styles.muted, style]}>{children}</Text>;
});

export const Badge = memo(function Badge({
  label, tone = 'accent',
}: { label: string; tone?: 'accent' | 'warn' | 'good' | 'bad' | 'muted' }) {
  const wrap =
    tone === 'warn' ? styles.badgeWarn
      : tone === 'good' ? styles.badgeGood
        : tone === 'bad' ? styles.badgeBad
          : tone === 'muted' ? styles.badgeMuted
            : styles.badgeAccent;
  const textColor =
    tone === 'warn' ? colors.warn
      : tone === 'good' ? colors.good
        : tone === 'bad' ? colors.bad
          : tone === 'muted' ? colors.muted
            : colors.accent;
  return (
    <View style={[styles.badge, wrap]}>
      <Text style={[styles.badgeText, { color: textColor }]}>{label}</Text>
    </View>
  );
});

export const PrimaryButton = memo(function PrimaryButton({
  label, onPress, disabled, tone = 'accent', style,
}: {
  label: string; onPress: () => void; disabled?: boolean;
  tone?: 'accent' | 'danger' | 'locked' | 'alt'; style?: ViewStyle;
}) {
  const bg =
    tone === 'danger' ? colors.bad
      : tone === 'locked' ? colors.locked
        : tone === 'alt' ? colors.cardAlt
          : colors.accent;
  return (
    <TouchableOpacity
      activeOpacity={0.85} disabled={disabled} onPress={onPress}
      style={[styles.btn, { backgroundColor: bg, opacity: disabled ? 0.5 : 1 }, style]}
    >
      <Text style={styles.btnText}>{label}</Text>
    </TouchableOpacity>
  );
});

export const SwitchRow = memo(function SwitchRow({
  label, value, onValueChange, trackColor,
}: {
  label: string; value: boolean; onValueChange: (v: boolean) => void;
  trackColor?: { true?: string; false?: string };
}) {
  return (
    <View style={styles.switchRow}>
      <Text style={styles.switchLabel}>{label}</Text>
      <Switch
        value={value}
        onValueChange={onValueChange}
        trackColor={{ false: colors.locked, true: trackColor?.true || colors.accent }}
        thumbColor={colors.white}
        ios_backgroundColor={colors.locked}
      />
    </View>
  );
});

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg },
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    padding: space.md + 2,
    marginBottom: space.sm + 2,
  },
  cardPressed: { backgroundColor: colors.cardHover, transform: [{ scale: 0.99 }] },
  section: {
    ...type.section,
    color: colors.muted,
    textTransform: 'uppercase',
    marginTop: space.md,
    marginBottom: space.sm,
  },
  title: { ...type.title, color: colors.text },
  muted: { ...type.meta, color: colors.muted },
  badge: {
    paddingHorizontal: space.sm,
    paddingVertical: 3,
    borderRadius: radius.pill,
    borderWidth: 1,
  },
  badgeAccent: { backgroundColor: colors.accentSoft, borderColor: colors.accentBorder },
  badgeWarn: { backgroundColor: colors.warnSoft, borderColor: 'rgba(240,180,41,0.35)' },
  badgeGood: { backgroundColor: colors.goodSoft, borderColor: 'rgba(61,214,140,0.35)' },
  badgeBad: { backgroundColor: colors.badSoft, borderColor: 'rgba(255,92,122,0.35)' },
  badgeMuted: { backgroundColor: colors.cardAlt, borderColor: colors.border },
  badgeText: { ...type.caption },
  btn: {
    paddingVertical: 14,
    paddingHorizontal: space.lg,
    borderRadius: radius.md,
    alignItems: 'center',
    marginTop: space.sm + 2,
  },
  btnText: { color: colors.white, fontWeight: '700', fontSize: 15 },
  switchRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: space.sm + 2,
    paddingVertical: 2,
  },
  switchLabel: { color: colors.textSecondary, flex: 1, marginRight: space.md, fontSize: 15 },
});
