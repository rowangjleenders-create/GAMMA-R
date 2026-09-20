import React, { memo, useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, TextInput, StyleSheet, FlatList, Switch, Alert,
  KeyboardAvoidingView, Platform, ActivityIndicator, Pressable, TouchableOpacity, Alert,
  ScrollView,
} from 'react-native'; // Platform check
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as Speech from 'expo-speech';
import { api } from '../api/client';
import { colors, space, radius } from '../theme/tokens';
import { Muted } from '../components/ui';

type Msg = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  meta?: string;
  proposals?: ProposalCard[];
  toolsUsed?: string[];
  sources?: string[];
  crashActive?: boolean;
  scoreboardSnippet?: string;
};

type ProposalCard = {
  symbol: string;
  strategy_id?: string;
  thesis?: string;
  risks?: string[];
  size_hint?: string;
  entry?: number | null;
  stop?: number | null;
  take_profit?: number | null;
  shares_hint?: number | null;
  requires_confirm?: boolean;
};

type SpeechRecModule = {
  requestPermissionsAsync: () => Promise<{ granted: boolean }>;
  start: (opts: Record<string, unknown>) => void;
  stop: () => void;
  abort?: () => void;
  addListener: (event: string, cb: (e: any) => void) => { remove: () => void };
};

function loadSpeechRec(): SpeechRecModule | null {
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const mod = require('expo-speech-recognition');
    return mod.ExpoSpeechRecognitionModule as SpeechRecModule;
  } catch {
    return null;
  }
}

const SpeechRec = loadSpeechRec();

const SUGGESTIONS = [
  'Command help',
  'Full desk brief',
  'Desk brief',
  'Portfolio risk',
  'Monitor',
  'Ahead of terminals',
  'Our edge',
  'vs other bots',
  'What to improve next',
  'Overnight research',
  'Daily self-critique',
  'Feed health / NBBO',
  'Pro chart',
  'Tape',
  'Custom scan',
  'Economic calendar',
  'Crash mode?',
  'Scoreboard keep/watch/cut',
  'Firewall status',
  'Research web',
  'What did you learn about macro',
];

const Bubble = memo(function Bubble({
  item,
  onInterrupt,
  onPaper,
  paperBusyId,
}: {
  item: Msg;
  onInterrupt: () => void;
  onPaper?: (p: ProposalCard) => void;
  paperBusyId?: string | null;
}) {
  return (
    <Pressable onPress={onInterrupt}>
      <View style={[styles.bubble, item.role === 'user' ? styles.userBubble : styles.botBubble]}>
        <View style={styles.roleRow}>
          <Text style={styles.role}>{item.role === 'user' ? 'You' : 'E-ve'}</Text>
          {item.crashActive ? (
            <View style={styles.crashBadge}><Text style={styles.crashBadgeText}>CRASH</Text></View>
          ) : null}
        </View>
        <Text style={styles.msg}>{item.content}</Text>
        {item.scoreboardSnippet ? (
          <Text style={styles.snippet}>Scoreboard: {item.scoreboardSnippet}</Text>
        ) : null}
        {item.toolsUsed && item.toolsUsed.length ? (
          <Text style={styles.meta}>tools: {item.toolsUsed.join(' → ')}</Text>
        ) : null}
        {item.sources && item.sources.length ? (
          <Text style={styles.meta}>sources: {item.sources.slice(0, 4).join(' · ')}</Text>
        ) : null}
        {item.meta ? <Text style={styles.meta}>{item.meta}</Text> : null}
        {(item.proposals || []).map((p) => {
          const key = `${p.symbol}-${p.strategy_id || 'na'}`;
          return (
            <View key={key} style={styles.proposalCard}>
              <Text style={styles.proposalTitle}>
                {p.symbol} · {p.strategy_id || 'strategy'}
              </Text>
              {p.thesis ? <Text style={styles.proposalBody}>{p.thesis}</Text> : null}
              {p.risks?.length ? (
                <Text style={styles.proposalRisks}>Risks: {p.risks.join('; ')}</Text>
              ) : null}
              {p.size_hint ? <Text style={styles.meta}>Size: {p.size_hint}</Text> : null}
              <TouchableOpacity
                style={styles.paperBtn}
                disabled={paperBusyId === key}
                onPress={() => onPaper?.(p)}
              >
                <Text style={styles.paperBtnText}>
                  {paperBusyId === key ? 'Submitting…' : 'Paper (firewall)'}
                </Text>
              </TouchableOpacity>
            </View>
          );
        })}
      </View>
    </Pressable>
  );
});

const Chip = memo(function Chip({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <TouchableOpacity style={styles.chip} onPress={onPress} activeOpacity={0.85}>
      <Text style={styles.chipText}>{label}</Text>
    </TouchableOpacity>
  );
});

export function CoPilotScreen() {
  const insets = useSafeAreaInsets();
  const [messages, setMessages] = useState<Msg[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        "GAMMA-R's E-ve assistant — beat retail signal bots on process/risk/learning. I am E-ve. Chips: Full desk brief · Portfolio risk · Our edge · vs other bots · Overnight · Daily self-critique. Tools cite regime+firewall+scoreboard; never claim L2 or live-audited returns. I will not tell you what to buy.",
    },
  ]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [handsFree, setHandsFree] = useState(false);
  const [sttReady] = useState(!!SpeechRec);
  const [interim, setInterim] = useState('');
  const [lastError, setLastError] = useState<string | null>(null);
  const [paperBusyId, setPaperBusyId] = useState<string | null>(null);

  const listRef = useRef<FlatList>(null);
  const handsFreeRef = useRef(false);
  const speakingRef = useRef(false);
  const listeningRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const sendRef = useRef<(raw: string) => Promise<void>>(async () => {});
  const listenRef = useRef<(fromHandsFree?: boolean) => Promise<void>>(async () => {});
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  useEffect(() => {
    handsFreeRef.current = handsFree;
  }, [handsFree]);

  const stopSpeech = useCallback(() => {
    try { Speech.stop(); } catch { /* ignore */ }
    speakingRef.current = false;
    setSpeaking(false);
  }, []);

  /** Instant interrupt — never waits on network or TTS. */
  const interruptNow = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    stopSpeech();
    try {
      SpeechRec?.abort?.();
      SpeechRec?.stop?.();
    } catch { /* ignore */ }
    listeningRef.current = false;
    setListening(false);
    setInterim('');
    setBusy(false);
  }, [stopSpeech]);

  const speak = useCallback((text: string) => {
    stopSpeech();
    const clipped = (text || '').slice(0, 1200);
    if (!clipped.trim()) return;
    speakingRef.current = true;
    setSpeaking(true);
    Speech.speak(clipped, {
      language: 'en-US',
      rate: 1.05,
      onDone: () => {
        speakingRef.current = false;
        setSpeaking(false);
        if (handsFreeRef.current) {
          setTimeout(() => listenRef.current(true), 350);
        }
      },
      onStopped: () => {
        speakingRef.current = false;
        setSpeaking(false);
      },
      onError: () => {
        speakingRef.current = false;
        setSpeaking(false);
      },
    });
  }, [stopSpeech]);

  const sendText = useCallback(async (raw: string) => {
    const text = (raw || '').trim();
    if (!text) return;
    interruptNow();
    setLastError(null);
    const userMsg: Msg = { id: `u-${Date.now()}`, role: 'user', content: text };
    setMessages((m) => [...m, userMsg]);
    setInput('');
    setInterim('');
    setBusy(true);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const history = [...messagesRef.current, userMsg]
        .filter((x) => x.id !== 'welcome')
        .slice(-8)
        .map((x) => ({ role: x.role, content: x.content }));
      const res = await api.copilot(text, history, ac.signal);
      if (ac.signal.aborted) return;
      const replyRaw = res.reply || 'No reply.';
      const reply = replyRaw
        .replace(/Firewall denied \(([^)]+)\):\s*/i, 'Blocked by risk firewall ($1): ')
        .replace(/session_gate/gi, 'market session closed')
        .replace(/max_notional/gi, 'order too large vs equity cap')
        .replace(/circuit_breaker/gi, 'circuit breaker halted entries')
        .replace(/crash_mode/gi, 'crash mode — aggressive entries paused');
      const content =
        res.disclaimer && !/not financial advice/i.test(reply)
          ? `${reply}\n\n_${res.disclaimer}_`
          : reply;
      const bits: string[] = [];
      if (res.source) bits.push(`source=${res.source}`);
      if (res.tools_used?.length) bits.push(`tools: ${res.tools_used.join(' → ')}`);
      if (res.strategy_plan?.active?.length) {
        bits.push(`plan: ${res.strategy_plan.active.slice(0, 6).join(', ')}${res.strategy_plan.regime_label ? ' · ' + res.strategy_plan.regime_label : ''}`);
      }
      if (res.memory_updated) bits.push('memory✓');
      const meta = bits.length ? bits.join(' · ') : undefined;
      const snip = (res as any).scoreboard_snippet?.strategies
        ?.slice(0, 3)
        ?.map((s: any) => `${s.strategy_id}:${s.status}`)
        .join(', ');
      setMessages((m) => [
        ...m,
        {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content,
          meta,
          proposals: (res as any).proposals || [],
          toolsUsed: (res as any).tools_used || (res as any).toolsUsed || [],
          sources: (res as any).sources || [],
          crashActive: !!(res as any).crash?.active,
          scoreboardSnippet: snip,
        },
      ]);
      requestAnimationFrame(() => speak(reply));
    } catch (e: any) {
      if (e?.name === 'AbortError' || ac.signal.aborted) return;
      const err = `E-ve error: ${e?.message || e}. Check Settings → API server.`;
      setLastError(err);
      setMessages((m) => [...m, { id: `e-${Date.now()}`, role: 'assistant', content: err }]);
    } finally {
      if (!ac.signal.aborted) setBusy(false);
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 80);
    }
  }, [interruptNow, speak]);

  useEffect(() => { sendRef.current = sendText; }, [sendText]);

  const stopListening = useCallback(() => {
    try {
      SpeechRec?.stop?.();
      SpeechRec?.abort?.();
    } catch { /* ignore */ }
    listeningRef.current = false;
    setListening(false);
    setInterim('');
  }, []);

  const startListening = useCallback(async (fromHandsFree = false) => {
    if (!SpeechRec) {
      if (!fromHandsFree) {
        Alert.alert(
          'Voice input needs a native build',
          'On-device STT is in your EAS/dev build (not plain Expo Go). Text chat + TTS still work.',
        );
      }
      return;
    }
    if (listeningRef.current) return;
    try {
      stopSpeech();
      const perm = await SpeechRec.requestPermissionsAsync();
      if (!perm?.granted) {
        Alert.alert('Mic permission', 'Enable Microphone and Speech Recognition in iOS Settings.');
        return;
      }
      listeningRef.current = true;
      setListening(true);
      setInterim('');
      SpeechRec.start({
        lang: 'en-US',
        interimResults: true,
        continuous: !!handsFreeRef.current,
        requiresOnDeviceRecognition: Platform.OS === 'ios',
      });
    } catch (e: any) {
      listeningRef.current = false;
      setListening(false);
      if (!fromHandsFree) Alert.alert('Speech recognition unavailable', String(e?.message || e));
    }
  }, [stopSpeech]);

  useEffect(() => { listenRef.current = startListening; }, [startListening]);

  useEffect(() => {
    if (!SpeechRec?.addListener) return;
    const subResult = SpeechRec.addListener('result', (event: any) => {
      const results = event?.results || [];
      const top = results[0];
      const transcript = String(top?.transcript || top?.[0]?.transcript || '').trim();
      const isFinal = Boolean(event?.isFinal ?? top?.isFinal ?? false);
      if (!transcript) return;
      if (speakingRef.current) stopSpeech();
      if (isFinal) {
        setInterim('');
        listeningRef.current = false;
        setListening(false);
        sendRef.current(transcript);
      } else {
        setInterim(transcript);
      }
    });
    const subEnd = SpeechRec.addListener('end', () => {
      listeningRef.current = false;
      setListening(false);
    });
    const subErr = SpeechRec.addListener('error', (e: any) => {
      listeningRef.current = false;
      setListening(false);
      const msg = String(e?.message || e?.error || '');
      if (msg && !/no.?speech|aborted/i.test(msg)) setLastError(`STT: ${msg}`);
    });
    return () => {
      subResult?.remove?.();
      subEnd?.remove?.();
      subErr?.remove?.();
      interruptNow();
    };
  }, [interruptNow, stopSpeech]);

  const onMicPress = () => {
    if (speaking || listening || busy) {
      interruptNow();
      return;
    }
    startListening(false);
  };


  const paperProposal = useCallback(async (p: ProposalCard) => {
    const key = `${p.symbol}-${p.strategy_id || 'na'}`;
    setPaperBusyId(key);
    try {
      const shares = Math.max(1, Math.floor(Number(p.shares_hint) || 1));
      let res: any;
      if (typeof (api as any).paperTrade === 'function') {
        res = await (api as any).paperTrade({
          ticker: p.symbol,
          shares,
          entry: p.entry ?? undefined,
          strategy_id: p.strategy_id,
          confirm: true,
        });
      } else {
        res = await api.copilot(
          `Submit paper order via firewall for ${p.symbol} shares=${shares} strategy_id=${p.strategy_id || 'momentum'} (confirm paper only)`,
          [],
        );
      }
      const denied =
        res?.ok === false ||
        res?.error ||
        res?.firewall?.allowed === false ||
        /denied|blocked|firewall/i.test(String(res?.reply || res?.reason || ''));
      const reason =
        res?.reason || res?.firewall?.reason || res?.error || res?.reply || 'blocked';
      if (denied) {
        Alert.alert('Firewall denied', String(reason).slice(0, 280));
        setMessages((m) => [
          ...m,
          {
            id: `fw-${Date.now()}`,
            role: 'assistant',
            content: `Paper (firewall) denied for ${p.symbol}: ${String(reason).slice(0, 240)}`,
          },
        ]);
      } else {
        Alert.alert('Paper submitted', `${p.symbol} × ${shares} via firewall`);
        setMessages((m) => [
          ...m,
          {
            id: `pf-${Date.now()}`,
            role: 'assistant',
            content: `Paper fill submitted for ${p.symbol} × ${shares} (strategy=${p.strategy_id || 'n/a'}). Educational only — not advice.`,
          },
        ]);
      }
    } catch (e: any) {
      Alert.alert('Paper failed', e?.message || String(e));
    } finally {
      setPaperBusyId(null);
    }
  }, []);

  const clearChat = () => {
    interruptNow();
    setMessages([
      {
        id: 'welcome',
        role: 'assistant',
        content: 'Chat cleared. Try scan status, learning summary, market hours, explain SIP, or how do fees work?',
      },
    ]);
    setLastError(null);
  };

  const renderItem = useCallback(
    ({ item }: { item: Msg }) => (
      <Bubble
        item={item}
        onInterrupt={interruptNow}
        onPaper={paperProposal}
        paperBusyId={paperBusyId}
      />
    ),
    [interruptNow, paperProposal, paperBusyId],
  );

  const showChips = messages.length <= 2 && !busy;

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 88 : 0}
    >
      <View style={styles.toolbar}>
        <View style={styles.switchRow}>
          <Text style={styles.toolLabel}>Hands-free</Text>
          <Switch
            value={handsFree}
            onValueChange={(v) => {
              setHandsFree(v);
              if (v) startListening(true);
              else stopListening();
            }}
            trackColor={{ false: colors.locked, true: colors.accent }}
            thumbColor={colors.white}
          />
          <TouchableOpacity onPress={clearChat} style={styles.clearBtn} hitSlop={8}>
            <Text style={styles.clearText}>Clear</Text>
          </TouchableOpacity>
        </View>
        <Text style={styles.toolHint}>
          {busy
            ? 'Thinking… tap mic to cancel'
            : speaking
              ? 'Speaking… tap mic or a bubble to stop'
              : listening
                ? 'Listening…'
                : sttReady
                  ? 'Mic ready (on-device STT)'
                  : 'TTS on · STT needs your EAS/iOS build'}
        </Text>
        {lastError ? <Text style={styles.errHint}>{lastError}</Text> : null}
      </View>

      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(m) => m.id}
        renderItem={renderItem}
        contentContainerStyle={{ padding: space.md, paddingBottom: space.sm, flexGrow: 1 }}
        initialNumToRender={12}
        windowSize={7}
        removeClippedSubviews
        onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
        ListEmptyComponent={<Muted>No messages — ask E-ve anything about your bot.</Muted>}
        ListFooterComponent={
          showChips ? (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.chips}
              keyboardShouldPersistTaps="handled"
            >
              {SUGGESTIONS.map((s) => (
                <Chip
                  key={s}
                  label={s}
                  onPress={() => {
                    const map: Record<string, string> = {
                      'Command help': 'Command help — desk GO bar examples (desk_command_help)',
                      'Full desk brief': 'Full desk brief — E-ve eve_desk_brief with regime top signals crash scoreboard overnight',
                      'Desk brief': 'Desk brief for SPY — E-ve AI news brief with sources (brief_news)',
                      'Portfolio risk': 'Portfolio risk snapshot — exposure concentration open brackets (portfolio_risk_snapshot)',
                      'Monitor': 'Run desk monitor — crash heat alerts scoreboard firewall overnight (run_monitor)',
                      'Ahead of terminals': 'Ahead of terminals vs Bloomberg/pro — AI desk supremacy; never claim BLP or L2 (get_competitive_gaps)',
                      'Our edge': 'Our edge — why GAMMA-R vs signal bots (use edge status)',
                      'Pro chart': 'Pro chart for SPY — OHLCV bars + VWAP (get_bars)',
                      'Tape': 'Tape lite for SPY — recent prints (get_tape)',
                      'Custom scan': 'Run a custom scan with volume/% change filters',
                      'Economic calendar': 'Show economic calendar rail events',
                      'vs other bots': 'vs other bots — competitive gaps closed vs still open',
                      'What to improve next': 'What to improve next — ranked suggestions from live health',
                      'Overnight research': 'Overnight research — summarize allowlisted web learning',
                      'Daily self-critique': 'Daily self-critique — scorecard strengths weaknesses next actions vs retail bots',
                      'Feed health / NBBO': 'Feed health / NBBO — Delayed IEX SIP or NBBO top-of-book?',
                      'Research web': 'Research web: recent macro and earnings news (educational)',
                    };
                    sendText(map[s] || s);
                  }}
                />
              ))}
            </ScrollView>
          ) : null
        }
      />

      {!!interim && <Text style={styles.interim}>Hearing: {interim}</Text>}
      {busy && (
        <View style={styles.busyRow}>
          <ActivityIndicator color={colors.accent} size="small" />
          <Text style={styles.toolHint}>Waiting for /copilot…</Text>
          <TouchableOpacity onPress={interruptNow} hitSlop={8}>
            <Text style={styles.clearText}>Cancel</Text>
          </TouchableOpacity>
        </View>
      )}

      <View style={[styles.composer, { paddingBottom: Math.max(space.sm + 2, insets.bottom > 0 ? 4 : space.sm + 2) }]}>
        <TouchableOpacity
          style={[styles.micBtn, listening && styles.micActive, speaking && styles.micSpeak]}
          onPress={onMicPress}
          accessibilityLabel="Microphone / interrupt"
        >
          <Text style={styles.micText}>{speaking || busy ? '⏹' : listening ? '⏺' : '🎤'}</Text>
        </TouchableOpacity>
        <TextInput
          style={styles.input}
          value={input}
          onChangeText={setInput}
          placeholder="Ask E-ve…"
          placeholderTextColor={colors.muted}
          multiline
          onSubmitEditing={() => sendText(input)}
        />
        <TouchableOpacity
          style={[styles.sendBtn, !input.trim() && { opacity: 0.45 }]}
          onPress={() => sendText(input)}
          disabled={!input.trim()}
        >
          <Text style={styles.sendText}>Send</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  toolbar: {
    paddingHorizontal: space.md,
    paddingVertical: space.sm + 2,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.borderSubtle,
    backgroundColor: colors.card,
  },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  toolLabel: { color: colors.text, fontWeight: '700', flex: 1 },
  toolHint: { color: colors.muted, fontSize: 11, marginTop: 6 },
  meta: { color: colors.muted, fontSize: 10, marginTop: 6, fontStyle: 'italic' },
  errHint: { color: colors.bad, fontSize: 11, marginTop: 4 },
  clearBtn: { paddingHorizontal: 8, paddingVertical: 4 },
  clearText: { color: colors.accent, fontWeight: '600', fontSize: 13 },
  chips: { paddingTop: space.sm, paddingBottom: space.xs, gap: space.sm },
  chip: {
    backgroundColor: colors.cardAlt,
    borderWidth: 1,
    borderColor: colors.accentBorder,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.pill,
    marginRight: space.sm,
  },
  chipText: { color: colors.accent, fontSize: 12, fontWeight: '600' },
  bubble: {
    borderRadius: radius.md,
    padding: space.md,
    marginBottom: space.sm,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  userBubble: { backgroundColor: colors.cardAlt, alignSelf: 'flex-end', maxWidth: '92%' },
  botBubble: { backgroundColor: colors.card, alignSelf: 'flex-start', maxWidth: '92%' },
  role: { color: colors.accent, fontSize: 11, fontWeight: '700', marginBottom: 4 },
  msg: { color: colors.text, fontSize: 15, lineHeight: 21 },
  interim: { color: colors.warn, fontSize: 12, paddingHorizontal: space.md, paddingBottom: 4 },
  busyRow: {
    flexDirection: 'row', alignItems: 'center', gap: space.sm,
    paddingHorizontal: space.md, paddingBottom: 4,
  },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: space.sm + 2,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.borderSubtle,
    backgroundColor: colors.card,
    gap: space.sm,
  },
  micBtn: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: colors.locked, alignItems: 'center', justifyContent: 'center',
  },
  micActive: { backgroundColor: colors.bad },
  micSpeak: { backgroundColor: colors.warn },
  micText: { fontSize: 18 },
  input: {
    flex: 1, minHeight: 44, maxHeight: 120,
    backgroundColor: colors.cardAlt, color: colors.text,
    borderRadius: radius.sm + 2, borderWidth: 1, borderColor: colors.borderSubtle,
    paddingHorizontal: space.md, paddingVertical: 10,
  },
  sendBtn: {
    backgroundColor: colors.accent, borderRadius: radius.sm + 2,
    paddingHorizontal: 14, paddingVertical: 12,
  },
  sendText: { color: colors.white, fontWeight: '700' },
  roleRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 4 },
  crashBadge: {
    backgroundColor: colors.bad, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 8,
  },
  crashBadgeText: { color: colors.white, fontSize: 10, fontWeight: '800' },
  snippet: { color: colors.muted, fontSize: 11, marginTop: 6 },
  proposalCard: {
    marginTop: 10, padding: 10, borderRadius: radius.sm,
    borderWidth: 1, borderColor: colors.accentBorder, backgroundColor: colors.cardAlt,
  },
  proposalTitle: { color: colors.accent, fontWeight: '700', marginBottom: 4 },
  proposalBody: { color: colors.text, fontSize: 13, lineHeight: 18 },
  proposalRisks: { color: colors.warn, fontSize: 11, marginTop: 4 },
  paperBtn: {
    marginTop: 8, alignSelf: 'flex-start', backgroundColor: colors.accent,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.sm,
  },
  paperBtnText: { color: colors.white, fontWeight: '700', fontSize: 12 },
});
