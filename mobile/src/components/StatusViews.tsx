import React, { memo } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, TouchableOpacity } from 'react-native';
import { colors, space, radius } from '../theme/tokens';

export const LoadingView = memo(function LoadingView({ label = 'Loading…' }: { label?: string }) {
  return (
    <View style={styles.center} accessibilityRole="progressbar">
      <ActivityIndicator color={colors.accent} />
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
});

export const EmptyView = memo(function EmptyView({
  title = 'Nothing here yet',
  hint,
  actionLabel,
  onAction,
  compact,
}: {
  title?: string;
  hint?: string;
  actionLabel?: string;
  onAction?: () => void;
  /** Nest inside lists without painting a second full-screen bg. */
  compact?: boolean;
}) {
  return (
    <View style={[styles.center, compact && styles.centerCompact]}>
      <Text style={styles.title}>{title}</Text>
      {hint ? <Text style={styles.muted}>{hint}</Text> : null}
      {actionLabel && onAction ? (
        <TouchableOpacity style={styles.btn} onPress={onAction} activeOpacity={0.85}>
          <Text style={styles.btnText}>{actionLabel}</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
});

export const ErrorBanner = memo(function ErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <View style={styles.errorBox} accessibilityRole="alert">
      <Text style={styles.errorText}>{message}</Text>
      {onRetry ? (
        <TouchableOpacity onPress={onRetry} style={styles.retry} hitSlop={8}>
          <Text style={styles.retryText}>Retry</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );
});

const styles = StyleSheet.create({
  center: {
    flex: 1, backgroundColor: colors.bg, alignItems: 'center', justifyContent: 'center', padding: space.xl,
  },
  centerCompact: { backgroundColor: 'transparent', paddingVertical: space.xxl },
  title: { color: colors.text, fontSize: 16, fontWeight: '700', textAlign: 'center' },
  muted: { color: colors.muted, marginTop: space.sm + 2, textAlign: 'center', fontSize: 13, lineHeight: 18 },
  btn: {
    marginTop: space.lg, backgroundColor: colors.accent, paddingHorizontal: space.lg,
    paddingVertical: 10, borderRadius: radius.md,
  },
  btnText: { color: colors.white, fontWeight: '700' },
  errorBox: {
    backgroundColor: colors.badSoft, borderColor: 'rgba(255,92,122,0.4)', borderWidth: 1,
    borderRadius: radius.md, padding: space.md, marginBottom: space.sm + 2,
  },
  errorText: { color: colors.bad, fontSize: 13, lineHeight: 18 },
  retry: { marginTop: space.sm, alignSelf: 'flex-start' },
  retryText: { color: colors.accent, fontWeight: '700' },
});
