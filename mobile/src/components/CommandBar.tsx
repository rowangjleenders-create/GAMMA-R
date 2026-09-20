import React, { useCallback, useRef, useState } from 'react';
import {
  View,
  TextInput,
  Text,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  Alert,
} from 'react-native';
import { api } from '../api/client';
import { colors, space, radius } from '../theme/tokens';

export type DeskRouteResult = {
  ok?: boolean;
  route?: string;
  action?: string;
  screen?: string;
  symbol?: string;
  interval?: string;
  prompt?: string;
  path?: string;
  error?: string;
  hint?: string;
  payload?: any;
  toast?: string;
};

type Props = {
  sticky?: boolean;
  onRoute?: (result: DeskRouteResult) => void;
  placeholder?: string;
};

const ROUTE_LABELS: Record<string, string> = {
  quote: 'Quote',
  chart: 'Chart',
  tape: 'Tape',
  ladder: 'Ladder',
  news: 'News',
  options: 'Options',
  eve: 'E-ve',
  brief: 'E-ve brief',
  scanner: 'Scanner',
  monitor: 'Monitor',
  help: 'Help',
};

function toastFor(res: DeskRouteResult): string {
  if (res?.toast) return res.toast;
  if (!res?.ok) {
    return res?.hint || res?.error || 'Command not recognized — try HELP';
  }
  const label = ROUTE_LABELS[res.route || ''] || (res.route || 'OK').toUpperCase();
  const sym = res.symbol ? ` · ${res.symbol}` : '';
  const interval = res.interval ? ` · ${res.interval}` : '';
  if (res.route === 'eve' && res.prompt) return `Opening E-ve · ${String(res.prompt).slice(0, 40)}`;
  if (res.route === 'monitor') return 'Monitor refreshed';
  if (res.route === 'help') return 'GO help — AAPL · NEWS · CHART · TAPE · OPT · EVE · SCAN · MONITOR';
  return `${label}${sym}${interval}`;
}

/** Bloomberg-inspired GO command bar — sticky on Pro / Dashboard. */
export function CommandBar({ sticky = true, onRoute, placeholder }: Props) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const inFlight = useRef(false);

  const go = useCallback(async () => {
    const cmd = text.trim();
    if (!cmd || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setHint(null);
    const NAV_ROUTES = new Set([
      'quote', 'chart', 'tape', 'ladder', 'news', 'options', 'eve', 'brief', 'scanner', 'monitor',
    ]);
    try {
      const res: DeskRouteResult = await api.deskCommand(cmd, true);
      const toast = toastFor(res);
      setHint(toast);
      const enriched = { ...res, toast };
      // Navigate first — avoid modal Alert blocking route changes
      onRoute?.(enriched);
      if (res?.ok && res?.route !== 'help') {
        setText('');
        // Non-blocking hint only for nav routes (Alert stole focus / delayed nav)
        if (!NAV_ROUTES.has(res.route || '')) {
          // stay with inline hint
        }
      } else if (!res?.ok) {
        Alert.alert('GO', toast);
      } else if (res?.route === 'help') {
        // keep command text; help is informational
      }
    } catch (e: any) {
      const msg = String(e?.message || e).slice(0, 120);
      setHint(msg);
      Alert.alert('GO failed', msg);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }, [text, onRoute]);

  return (
    <View style={[styles.wrap, sticky && styles.sticky]} accessibilityRole="search">
      <View style={styles.row}>
        <Text style={styles.go} accessibilityLabel="Desk GO command">GO</Text>
        <TextInput
          style={styles.input}
          value={text}
          onChangeText={setText}
          placeholder={placeholder || 'AAPL · NEWS AAPL · CHART AAPL 15m · EVE …'}
          placeholderTextColor={colors.muted}
          autoCapitalize="characters"
          autoCorrect={false}
          returnKeyType="go"
          onSubmitEditing={go}
          accessibilityLabel="Desk command input"
          accessibilityHint="Enter symbol or NEWS, CHART, TAPE, OPT, EVE, SCAN, MONITOR"
        />
        <TouchableOpacity
          style={styles.btn}
          onPress={go}
          disabled={busy || !text.trim()}
          accessibilityRole="button"
          accessibilityLabel="Run GO command"
        >
          {busy ? (
            <ActivityIndicator color={colors.white} size="small" />
          ) : (
            <Text style={styles.btnText}>↵</Text>
          )}
        </TouchableOpacity>
      </View>
      {hint ? (
        <Text style={styles.hint} accessibilityLiveRegion="polite">{hint}</Text>
      ) : null}
      <Text style={styles.cap}>Desk GO — not Bloomberg licensed · not L2</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: colors.card,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.borderSubtle,
    paddingHorizontal: space.md,
    paddingTop: space.sm,
    paddingBottom: space.xs,
  },
  sticky: { zIndex: 20 },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  go: {
    color: colors.accent,
    fontWeight: '800',
    fontSize: 12,
    letterSpacing: 1,
    minWidth: 28,
  },
  input: {
    flex: 1,
    backgroundColor: colors.cardAlt,
    borderWidth: 1,
    borderColor: colors.accentBorder,
    borderRadius: radius.sm,
    color: colors.text,
    paddingHorizontal: 10,
    paddingVertical: 8,
    fontSize: 14,
    fontWeight: '600',
  },
  btn: {
    backgroundColor: colors.accent,
    borderRadius: radius.sm,
    paddingHorizontal: 14,
    paddingVertical: 8,
    minWidth: 40,
    alignItems: 'center',
  },
  btnText: { color: colors.white, fontWeight: '800', fontSize: 16 },
  hint: { color: colors.muted, fontSize: 11, marginTop: 4 },
  cap: { color: colors.muted, fontSize: 9, marginTop: 2, opacity: 0.8 },
});
