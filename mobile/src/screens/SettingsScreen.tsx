import React, { memo, useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, SectionList, TextInput, StyleSheet, Switch, TouchableOpacity, Alert,
} from 'react-native';
import {
  api, getBaseUrl, setBaseUrl, getLocalBaseUrl, getOwnerSecret, setOwnerSecret, isLocalApiHost,
  getRemoteAccessEnabled, setRemoteAccessEnabled, getRemoteApiUrl, setRemoteApiUrl,
} from '../api/client';
import { colors, space, radius, type } from '../theme/tokens';
import {
  clearAlpacaKeys, isLiveUnlocked, loadAlpacaKeys, saveAlpacaKeys, setLiveUnlocked,
  getSipPrefLocal, setSipPrefLocal,
} from '../services/secureKeys';
import AsyncStorage from '../api/storage';
import { InstallQrModal } from '../components/InstallQrModal';

const INSTALL_URL_KEY = 'installPageUrl';
const DEFAULT_INSTALL_URL = 'http://localhost:3333/install.html';

type Row =
  | { id: string; kind: 'hint'; text: string }
  | { id: string; kind: 'warn'; text: string }
  | { id: string; kind: 'num'; key: string; label: string }
  | { id: string; kind: 'toggle'; key: string; label: string }
  | { id: string; kind: 'text'; key: string; placeholder?: string; secure?: boolean; autoCap?: 'none' | 'characters' }
  | { id: string; kind: 'baseUrl' }
  | { id: string; kind: 'ownerSecret' }
  | { id: string; kind: 'remoteToggle' }
  | { id: string; kind: 'remoteUrl' }
  | { id: string; kind: 'paperMode' }
  | { id: string; kind: 'sip' }
  | { id: string; kind: 'installUrl' }
  | { id: string; kind: 'btn'; label: string; action: string; tone?: 'accent' | 'locked' | 'danger' }
  | { id: string; kind: 'liveBlock' }
  | { id: string; kind: 'dataStatus' }
  | { id: string; kind: 'autoStatus' }
  | { id: string; kind: 'stratToggle'; strategyId: string; label: string }
  | { id: string; kind: 'stratHint' };

const SectionHeader = memo(function SectionHeader({ title }: { title: string }) {
  return <Text style={styles.section}>{title}</Text>;
});

export function SettingsScreen() {
  const [cfg, setCfg] = useState<Record<string, any>>({});
  const [base, setBase] = useState('http://localhost:8000');
  const [paperMode, setPaperMode] = useState(true);
  const [liveUnlocked, setLiveUnlockedState] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [brokerStatus, setBrokerStatus] = useState<any>(null);
  const [installOpen, setInstallOpen] = useState(false);
  const [installPageUrl, setInstallPageUrl] = useState(DEFAULT_INSTALL_URL);
  const [sipEnabled, setSipEnabled] = useState(false);
  const [dataSourceStatus, setDataSourceStatus] = useState<any>(null);
  const [ownerSecret, setOwnerSecretState] = useState('');
  const [healthHint, setHealthHint] = useState<string | null>(null);
  const [apiSecured, setApiSecured] = useState<'yes' | 'no' | 'unknown'>('unknown');
  const [remoteNoSecretWarn, setRemoteNoSecretWarn] = useState(false);
  const [remoteEnabled, setRemoteEnabled] = useState(false);
  const [remoteUrl, setRemoteUrl] = useState('');
  const [remoteStatusHint, setRemoteStatusHint] = useState<string | null>(null);
  const [autoStatus, setAutoStatus] = useState<any>(null);
  const [packs, setPacks] = useState<any[]>([]);
  const [coverage, setCoverage] = useState<any | null>(null);
  const [packBusy, setPackBusy] = useState<string | null>(null);
  const [brokersCard, setBrokersCard] = useState<any | null>(null);
  const [alpacaTestBusy, setAlpacaTestBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const local = await getLocalBaseUrl();
      setBase(local);
      const remOn = await getRemoteAccessEnabled();
      const remUrl = await getRemoteApiUrl();
      setRemoteEnabled(remOn);
      setRemoteUrl(remUrl);
      const effective = await getBaseUrl();
      const sec = await getOwnerSecret();
      setOwnerSecretState(sec);
      setRemoteNoSecretWarn(!isLocalApiHost(effective) && !sec);
      const savedInstall = await AsyncStorage.getItem(INSTALL_URL_KEY);
      if (savedInstall) setInstallPageUrl(savedInstall);
      try {
        setCfg(await api.getConfig());
        const perf = await api.portfolio();
        setPaperMode(perf.mode !== 'live');
      } catch { /* first launch */ }
      setLiveUnlockedState(await isLiveUnlocked());
      const keys = await loadAlpacaKeys();
      if (keys) {
        setApiKey(keys.apiKey);
        setApiSecret('••••••••');
      }
      try {
        const bs = await api.brokersStatus().catch(() => api.brokerStatus());
        setBrokerStatus(bs);
        setBrokersCard(bs);
      } catch { /* optional */ }
      try { setAutoStatus(await api.autoStatus()); } catch { /* optional */ }
      try {
        const pr = await api.strategiesPacks();
        setPacks(pr.packs || pr || []);
      } catch { /* optional */ }
      try { setCoverage(await api.marketsCoverage()); } catch { /* optional */ }
      try {
        const ds = await api.dataSourceStatus();
        setDataSourceStatus(ds);
        setSipEnabled(!!ds.realtime_sip_enabled);
        setCfg((prev) => ({ ...prev, realtime_sip_enabled: !!ds.realtime_sip_enabled }));
      } catch {
        setSipEnabled(await getSipPrefLocal());
      }
    })();
  }, []);

  const setNum = useCallback((key: string, t: string) => {
    setCfg((c) => ({ ...c, [key]: t === '' ? '' : Number(t) }));
  }, []);

  const setToggle = useCallback((key: string, v: boolean) => {
    setCfg((c) => ({ ...c, [key]: v }));
  }, []);

  const setStrategyToggle = useCallback((strategyId: string, v: boolean) => {
    setCfg((c) => ({
      ...c,
      strategy_enabled: { ...(c.strategy_enabled || {}), [strategyId]: v },
    }));
  }, []);

  const setText = useCallback((key: string, t: string) => {
    setCfg((c) => ({ ...c, [key]: t }));
  }, []);

  const save = useCallback(async () => {
    try {
      await setBaseUrl(base);
      await setRemoteAccessEnabled(remoteEnabled);
      await setRemoteApiUrl(remoteUrl);
      await setOwnerSecret(ownerSecret);
      const effective = remoteEnabled && remoteUrl.trim() ? remoteUrl.trim().replace(/\/$/, '') : base;
      setRemoteNoSecretWarn(!isLocalApiHost(effective) && !(ownerSecret || '').trim());
      if (remoteEnabled && !(ownerSecret || '').trim()) {
        Alert.alert('Remote access', 'Owner secret required when using a remote URL. Set the same secret as the server.');
      }
      const cleaned: Record<string, any> = {};
      for (const [k, v] of Object.entries(cfg)) {
        if (v !== '' && v !== undefined) cleaned[k] = v;
      }
      await api.putConfig(cleaned);
      await api.setMode(paperMode ? 'paper' : 'live');
      if (typeof cleaned.realtime_sip_enabled === 'boolean') {
        await api.setDataSource(!!cleaned.realtime_sip_enabled);
        await setSipPrefLocal(!!cleaned.realtime_sip_enabled);
      }
      Alert.alert('Saved', 'Config + API URL updated');
    } catch (e: any) {
      Alert.alert('Save failed', e.message);
    }
  }, [base, ownerSecret, cfg, paperMode, remoteEnabled, remoteUrl]);

  const saveInstallUrl = useCallback(async () => {
    const v = installPageUrl.trim() || DEFAULT_INSTALL_URL;
    setInstallPageUrl(v);
    await AsyncStorage.setItem(INSTALL_URL_KEY, v);
    Alert.alert('Saved', 'Install page URL stored for the QR code');
  }, [installPageUrl]);

  const toggleSip = useCallback(async (v: boolean) => {
    const prev = sipEnabled;
    setSipEnabled(v);
    setCfg((c) => ({ ...c, realtime_sip_enabled: v }));
    await setSipPrefLocal(v);
    try {
      const st = await api.setDataSource(v);
      setDataSourceStatus(st);
      if (v) {
        Alert.alert(
          'Real-time SIP',
          'Requires Alpaca API key + paid Algo Trader Plus (~$99/mo). Keys stay in SecureStore. Historical training still uses free delayed data.',
        );
      }
    } catch (e: any) {
      setSipEnabled(prev);
      setCfg((c) => ({ ...c, realtime_sip_enabled: prev }));
      await setSipPrefLocal(prev);
      Alert.alert('Data source', e.message || 'Failed to update server');
    }
  }, [sipEnabled]);

  const unlockLive = useCallback(() => {
    Alert.alert(
      '⚠️ REAL MONEY RISK',
      'Live trading can lose real money. Keys are stored in the device Keychain/Keystore only. Backend stays OFF unless LIVE_TRADING_ENABLED=1. Continue?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'I understand — unlock',
          style: 'destructive',
          onPress: async () => {
            await setLiveUnlocked(true);
            setLiveUnlockedState(true);
          },
        },
      ],
    );
  }, []);

  const saveKeys = useCallback(async () => {
    if (!apiKey || apiSecret.startsWith('••')) {
      Alert.alert('Enter both API key and secret');
      return;
    }
    await saveAlpacaKeys(apiKey, apiSecret);
    Alert.alert('Saved securely', 'Keys stored via expo-secure-store (not plain text).');
  }, [apiKey, apiSecret]);

  const kill = useCallback(async () => {
    try {
      const r = await api.brokerKill();
      Alert.alert('Kill switch', JSON.stringify(r));
    } catch (e: any) {
      Alert.alert('Kill switch', e.message);
    }
  }, []);


  const applyPack = async (packId: string, packName?: string) => {
    setPackBusy(packId);
    try {
      let previewNote = '';
      try {
        const prev = await api.previewStrategyPack(packId);
        const on = (prev?.toggles_on || []).join(', ') || '—';
        const off = (prev?.toggles_off || []).join(', ') || '—';
        const tweaks = Object.keys(prev?.config_tweaks || {}).join(', ') || '—';
        const beats = prev?.pack?.beats_at || '';
        previewNote = [
          beats ? `Beats: ${beats}` : '',
          `ON: ${on}`,
          `OFF: ${off}`,
          `Tweaks: ${tweaks}`,
        ].filter(Boolean).join('\n');
      } catch { /* preview optional */ }

      const confirmed = await new Promise<boolean>((resolve) => {
        Alert.alert(
          `Apply ${packName || packId}?`,
          `${previewNote || 'Apply strategy pack (paper-first).'}\n\nLive trading stays locked.`,
          [
            { text: 'Cancel', style: 'cancel', onPress: () => resolve(false) },
            { text: 'Apply', onPress: () => resolve(true) },
          ],
        );
      });
      if (!confirmed) {
        setPackBusy(null);
        return;
      }

      const r = await api.applyStrategyPack(packId);
      if (r?.strategy_enabled) {
        setCfg((c: any) => ({ ...c, strategy_enabled: r.strategy_enabled }));
      }
      try { setCfg(await api.getConfig()); } catch { /* ignore */ }
      Alert.alert(
        'Pack applied',
        `${packName || packId}\n${r?.note || 'strategy_enabled updated (paper-first).'}`,
      );
    } catch (e: any) {
      Alert.alert('Pack failed', e?.message || String(e));
    } finally {
      setPackBusy(null);
    }
  };

  const onAction = useCallback(async (action: string) => {
    try {
      if (action === 'testAlpaca') {
        setAlpacaTestBusy(true);
        try {
          const r = await api.testAlpacaBroker(true);
          Alert.alert(
            r?.ok ? 'Alpaca OK' : 'Alpaca test failed',
            r?.ok
              ? `Paper equity: ${r.equity ?? '—'} (${r.endpoint || 'paper'})`
              : String(r?.error || JSON.stringify(r)).slice(0, 280),
          );
          try { setBrokersCard(await api.brokersStatus()); } catch { /* */ }
        } catch (e: any) {
          Alert.alert('Alpaca test', e?.message || String(e));
        } finally {
          setAlpacaTestBusy(false);
        }
        return;
      }
      if (typeof action === 'string' && action.startsWith('pack:')) {
        const pid = action.slice(5);
        const pack = (packs || []).find((x: any) => x.id === pid);
        await applyPack(pid, pack?.name);
        return;
      }
      if (action === 'ping') {
        const t0 = Date.now();
        const h = await api.health();
        const ms = Date.now() - t0;
        let auth = 'unknown';
        let hardened: any = undefined;
        try {
          const st = await api.ownerStatus();
          auth = String(st.auth || 'unknown');
          hardened = st.hardened;
          const secured = auth === 'shared_secret' || auth === 'hardened_missing_secret' || auth === 'required_missing'
            ? 'yes' : auth === 'open' ? 'no' : 'unknown';
          setApiSecured(secured as 'yes' | 'no' | 'unknown');
        } catch {
          /* /health is public; ownerStatus may 401 without secret */
          setApiSecured(ownerSecret ? 'yes' : 'unknown');
        }
        const msg = `OK · ${h.status || 'up'} · auth=${auth}${hardened != null ? ` · hardened=${hardened}` : ''} · ${ms}ms · ${base}`;
        setHealthHint(msg);
        Alert.alert('API health', msg);
        return;
      }
      if (action === 'testRemote') {
        await setRemoteAccessEnabled(remoteEnabled);
        await setRemoteApiUrl(remoteUrl);
        await setOwnerSecret(ownerSecret);
        if (remoteEnabled && !remoteUrl.trim()) {
          Alert.alert('Remote access', 'Set a remote API URL first (Tailscale / Cloudflare / SSH).');
          return;
        }
        if (remoteEnabled && !(ownerSecret || '').trim()) {
          Alert.alert('Remote access', 'Owner secret required for remote. Same value as OWNER_SHARED_SECRET / data/.owner_secret.');
        }
        const t0 = Date.now();
        const st = await api.remoteStatus();
        const ms = Date.now() - t0;
        let sessionOk = '';
        try {
          const sess = await api.remoteSession('mobile-settings');
          sessionOk = sess?.ok ? 'session=ok' : 'session=?';
        } catch (e: any) {
          sessionOk = `session=${e?.message || 'fail'}`.slice(0, 80);
        }
        const msg = [
          `remote_access=${st.remote_access_enabled}`,
          `hardened=${st.hardened}`,
          `auth=${st.auth}`,
          `secret_required=${st.secret_required}`,
          `live_locked=${st.live_locked}`,
          `prefer_tunnel=${st.prefer_tunnel}`,
          sessionOk,
          `${ms}ms`,
          await getBaseUrl(),
        ].join(' · ');
        setRemoteStatusHint(msg);
        setApiSecured(
          st.auth === 'shared_secret' || st.secret_required ? 'yes' : st.auth === 'open' ? 'no' : 'unknown',
        );
        Alert.alert('Remote connection', msg);
        return;
      }
      if (action === 'ownerStatus') {
        const st = await api.ownerStatus();
        const auth = String(st.auth || '');
        setApiSecured(auth === 'shared_secret' || auth === 'required_missing' ? 'yes' : auth === 'open' ? 'no' : 'unknown');
        Alert.alert('Owner status', `auth=${st.auth} · hardened=${st.hardened} · signals=${st.cached_signals} · live=${st.live_trading_enabled}`);
        return;
      }
      if (action === 'exportWatch') {
        const ex = await api.ownerExport('watchlist');
        Alert.alert('Watchlist exported', JSON.stringify(ex.content).slice(0, 200));
        return;
      }
      if (action === 'cbFalse') {
        const r = await api.circuitFalseTrip('settings');
        setAutoStatus(await api.autoStatus());
        Alert.alert('Circuit breaker', r.explanation || JSON.stringify(r).slice(0, 200));
        return;
      }
      if (action === 'cbMiss') {
        const r = await api.circuitMissedBad('settings');
        setAutoStatus(await api.autoStatus());
        Alert.alert('Circuit breaker', r.explanation || JSON.stringify(r).slice(0, 200));
        return;
      }
      if (action === 'cbResume') {
        const r = await api.circuitResume('settings');
        setAutoStatus(await api.autoStatus());
        Alert.alert('Circuit breaker', r.explanation || 'resumed');
        return;
      }
      if (action === 'exportPaper') {
        const ex = await api.ownerExport('paper');
        const c = ex.content || {};
        Alert.alert(
          'Paper snapshot',
          `equity=${c.equity ?? '?'} cash=${c.cash ?? '?'} open=${(c.open_positions || c.positions || []).length}`,
        );
        return;
      }
      if (action === 'install') {
        setInstallOpen(true);
        return;
      }
      if (action === 'save') {
        await save();
        return;
      }
      if (action === 'unlockLive') {
        unlockLive();
        return;
      }
      if (action === 'saveKeys') {
        await saveKeys();
        return;
      }
      if (action === 'kill') {
        await kill();
        return;
      }
      if (action === 'lockLive') {
        await setLiveUnlocked(false);
        await clearAlpacaKeys();
        setLiveUnlockedState(false);
        setApiKey('');
        setApiSecret('');
        return;
      }
      if (action === 'saveInstall') {
        await saveInstallUrl();
      }
    } catch (e: any) {
      Alert.alert('Action failed', e.message || String(e));
    }
  }, [base, save, unlockLive, saveKeys, kill, saveInstallUrl, packs, remoteEnabled, remoteUrl, ownerSecret]);


  const sections = useMemo(() => {
    const apiRows: Row[] = [
      { id: 'api-hint', kind: 'hint', text: 'LAN IP for a physical iPhone (e.g. http://192.168.1.10:8000) or localhost on Simulator. Prefer Tailscale/VPN; never expose the API to the public internet without TLS + secret.' },
      { id: 'base', kind: 'baseUrl' },
      { id: 'secured', kind: 'hint', text: `API secured: ${apiSecured === 'unknown' ? '—' : apiSecured} (client secret ${ownerSecret ? 'set' : 'not set'}; server auth from /owner/status — /health is minimal)` },
      ...(remoteNoSecretWarn
        ? [{ id: 'remote-warn', kind: 'warn' as const, text: 'Connecting to a non-localhost API without an owner secret. Set the same OWNER_SHARED_SECRET in Settings (sent as X-Owner-Secret header only).' }]
        : []),
      { id: 'secret-hint', kind: 'hint', text: 'Owner secret (SecureStore). Required when server has OWNER_SHARED_SECRET / data/.owner_secret. Sent as X-Owner-Secret — never as a URL query.' },
      { id: 'secret', kind: 'ownerSecret' },
      ...(healthHint ? [{ id: 'health', kind: 'hint' as const, text: healthHint }] : []),
      { id: 'ping', kind: 'btn', label: 'Ping /health', action: 'ping', tone: 'locked' },
      { id: 'owner', kind: 'btn', label: 'Check /owner/status', action: 'ownerStatus', tone: 'locked' },
      { id: 'exw', kind: 'btn', label: 'Export watchlist (data/)', action: 'exportWatch', tone: 'locked' },
      { id: 'exp', kind: 'btn', label: 'Peek paper export', action: 'exportPaper', tone: 'locked' },
    ];

    const remoteRows: Row[] = [
      { id: 'ra-hint', kind: 'hint', text: 'Reach your API away from home via Tailscale, Cloudflare Tunnel, or SSH — not a naked public IP. Live trading stays locked.' },
      { id: 'ra-toggle', kind: 'remoteToggle' },
      { id: 'ra-url-hint', kind: 'hint', text: 'Remote API URL (e.g. http://100.x.y.z:8000 Tailscale or https://… Cloudflare). Stored in SecureStore.' },
      { id: 'ra-url', kind: 'remoteUrl' },
      { id: 'ra-secret-hint', kind: 'hint', text: 'Owner secret (same SecureStore field as API server). Required for remote — sent as X-Owner-Secret only.' },
      { id: 'ra-secret', kind: 'ownerSecret' },
      ...(remoteEnabled && !(ownerSecret || '').trim()
        ? [{ id: 'ra-warn-secret', kind: 'warn' as const, text: 'Remote enabled without owner secret — server will reject non-/health routes when hardened.' }]
        : []),
      ...(remoteEnabled && remoteUrl.trim() && !/^https?:\/\//i.test(remoteUrl.trim())
        ? [{ id: 'ra-warn-scheme', kind: 'warn' as const, text: 'Remote URL should start with http:// or https://' }]
        : []),
      ...(remoteEnabled && /\b(?:\d{1,3}\.){3}\d{1,3}\b/.test(remoteUrl) && !remoteUrl.includes('100.')
        ? [{ id: 'ra-warn-ip', kind: 'warn' as const, text: 'Prefer Tailscale (100.x) / Cloudflare / SSH tunnel over a naked public IP.' }]
        : []),
      ...(remoteStatusHint ? [{ id: 'ra-status', kind: 'hint' as const, text: remoteStatusHint }] : []),
      { id: 'ra-test', kind: 'btn', label: 'Test remote connection', action: 'testRemote', tone: 'accent' },
      { id: 'ra-docs', kind: 'hint', text: 'Server: REMOTE_ACCESS_ENABLED=1 + OWNER_SHARED_SECRET. Docs: docs/REMOTE_ACCESS.md' },
    ];

    const installRows: Row[] = [
      { id: 'inst-hint', kind: 'hint', text: 'Private install only (TestFlight / sideload / Expo Go). Show a QR for your install page — host mobile/web/install.html or run npm run install-page.' },
      { id: 'inst-btn', kind: 'btn', label: 'Install QR', action: 'install' },
      { id: 'inst-url', kind: 'installUrl' },
    ];

    const paperRows: Row[] = [
      { id: 'paper', kind: 'paperMode' },
      ...(!paperMode
        ? [{ id: 'paper-warn', kind: 'warn' as const, text: 'Live mode label only unless LIVE_TRADING_ENABLED — not connected to a broker by default.' }]
        : []),
    ];

    const momentum: Row[] = [
      { id: 'lb', kind: 'num', key: 'lookback_days', label: 'Lookback days (seed 10)' },
      { id: 'vm', kind: 'num', key: 'volume_multiple', label: 'Volume multiple (seed 1.5)' },
      { id: 'vad', kind: 'num', key: 'volume_avg_days', label: 'Volume avg days (seed 20)' },
      { id: 'tpct', kind: 'num', key: 'top_pct', label: 'Top pct gainers (seed 0.10 = top 10%)' },
      { id: 'mr', kind: 'num', key: 'min_return', label: 'Min return' },
      { id: 'sl', kind: 'num', key: 'stop_loss_pct', label: 'Stop-loss pct (seed 0.05)' },
      { id: 'tp', kind: 'num', key: 'take_profit_pct', label: 'Take-profit pct (seed 0.15)' },
      { id: 'rpt', kind: 'num', key: 'risk_per_trade', label: 'Risk per trade' },
      { id: 'mpp', kind: 'num', key: 'max_position_pct', label: 'Max position pct' },
      { id: 'mp', kind: 'num', key: 'min_price', label: 'Min price (penny filter)' },
      { id: 'se', kind: 'num', key: 'starting_equity', label: 'Starting equity' },
    ];

    const advanced: Row[] = [
      { id: 'adx', kind: 'toggle', key: 'require_adx', label: 'Require ADX' },
      { id: 'madx', kind: 'num', key: 'min_adx', label: 'Min ADX' },
      { id: 'ma', kind: 'toggle', key: 'require_ma_alignment', label: 'MA alignment' },
      { id: 'mrv', kind: 'num', key: 'max_realized_vol', label: 'Max realized vol' },
      { id: 'uts', kind: 'toggle', key: 'use_trailing_stop', label: 'Trailing stop' },
      { id: 'tsp', kind: 'num', key: 'trailing_stop_pct', label: 'Trailing stop pct' },
      { id: 'upp', kind: 'toggle', key: 'use_partial_profits', label: 'Partial profits' },
      { id: 'ptp', kind: 'num', key: 'partial_take_pct', label: 'Partial take at gain pct' },
      { id: 'ted', kind: 'num', key: 'time_exit_days', label: 'Time exit days' },
    ];

    const regime: Row[] = [
      { id: 'urf', kind: 'toggle', key: 'use_regime_filter', label: 'Regime filter' },
      { id: 'ue', kind: 'toggle', key: 'use_ensemble', label: 'Ensemble models' },
      { id: 'ufe', kind: 'toggle', key: 'use_forward_estimate', label: 'Forward estimate gate' },
      { id: 'fet', kind: 'num', key: 'forward_estimate_threshold', label: 'Forward prob threshold' },
      { id: 'emv', kind: 'num', key: 'ensemble_min_votes', label: 'Ensemble min votes' },
    ];

    const news: Row[] = [
      { id: 'uns', kind: 'toggle', key: 'use_news_sentiment', label: 'Use news sentiment' },
      { id: 'ucp', kind: 'toggle', key: 'use_currency_panel', label: 'Show currency (FX) panel' },
      { id: 'nbh', kind: 'hint', text: 'Blend: 70_30 (default), 50_50, or technical_only' },
      { id: 'nbm', kind: 'text', key: 'news_blend_mode', placeholder: '70_30', autoCap: 'none' },
      { id: 'nw', kind: 'num', key: 'news_weight', label: 'News weight (0=tech-only, 0.3≈70/30, 0.5=50/50)' },
    ];

    const tz: Row[] = [
      { id: 'tzh', kind: 'hint', text: 'IANA TZ e.g. America/Chicago. Market default America/New_York.' },
      { id: 'utz', kind: 'text', key: 'user_timezone', autoCap: 'none' },
      { id: 'mex', kind: 'text', key: 'market_exchange', autoCap: 'characters' },
      { id: 'aah', kind: 'toggle', key: 'allow_after_hours_signals', label: 'Allow / label after-hours signals' },
      { id: 'odo', kind: 'toggle', key: 'only_act_during_open', label: 'Only act during regular hours' },
    ];

    const fees: Row[] = [
      { id: 'fh', kind: 'hint', text: 'ON by default so paper P&L looks realistic. Applied on entry and exit. Default: $0.005/share + 0.1% slippage.' },
      { id: 'fe', kind: 'toggle', key: 'fees_enabled', label: 'Charge fees on paper trades' },
      { id: 'cmh', kind: 'hint', text: 'Commission mode: per_share or flat' },
      { id: 'cm', kind: 'text', key: 'commission_mode', autoCap: 'none' },
      { id: 'cps', kind: 'num', key: 'commission_per_share', label: 'Commission per share (default 0.005)' },
      { id: 'cf', kind: 'num', key: 'commission_flat', label: 'Flat commission per trade (default 1.0)' },
      { id: 'sp', kind: 'num', key: 'slippage_pct', label: 'Slippage pct of trade value (default 0.001 = 0.1%)' },
    ];

    const data: Row[] = [
      { id: 'sip', kind: 'sip' },
      { id: 'dsh', kind: 'hint', text: `Feed badge: ${dataSourceStatus?.feed_badge || (sipEnabled ? 'SIP/IEX' : 'Delayed')} · Delayed|IEX|SIP|NBBO · top-of-book only, not Level-2 depth. Free delayed default; SIP/IEX optional. Fallback clearly labeled Delayed.` },
      { id: 'ds', kind: 'dataStatus' },
      { id: 'dscheck', kind: 'hint', text: (dataSourceStatus?.enable_checklist || []).map((c: any) => `${c.done ? '✓' : '○'} ${c.label}`).join(' · ') || 'Checklist loads with /data-source/status' },
      ...(sipEnabled
        ? [{ id: 'sipw', kind: 'warn' as const, text: 'Store Alpaca keys below (or in Live Trading). Same SecureStore path. Server also reads ALPACA_API_KEY / ALPACA_API_SECRET.' }]
        : []),
    ];

    const live: Row[] = [
      { id: 'lw', kind: 'warn', text: 'Off by default. Real money. Server still needs LIVE_TRADING_ENABLED=1. Keys stay in SecureStore / Keychain — never logged.' },
      { id: 'live', kind: 'liveBlock' },
    ];

    const autoRows: Row[] = [
      { id: 'autoh', kind: 'hint', text: 'Unattended loops start with the API server. Paper auto-trade by default; live only if LIVE_TRADING_ENABLED is already set on the server.' },
      { id: 'ale', kind: 'toggle', key: 'auto_learn_enabled', label: 'Auto-learn (journal → thresholds)' },
      { id: 'ate', kind: 'toggle', key: 'auto_trade_enabled', label: 'Auto-trade (paper scan→act)' },
      { id: 'ali', kind: 'num', key: 'auto_learn_interval_minutes', label: 'Learn interval (minutes)' },
      { id: 'ati', kind: 'num', key: 'auto_trade_interval_minutes', label: 'Trade interval (minutes)' },
      { id: 'asi', kind: 'num', key: 'auto_scan_interval_minutes', label: 'Auto-scan interval (minutes, freshness)' },
      { id: 'sttl', kind: 'num', key: 'scan_cache_ttl_sec', label: 'Scan cache TTL (seconds)' },
      { id: 'sstale', kind: 'num', key: 'scan_stale_warn_sec', label: 'Stale warning after (seconds)' },
      { id: 'qse', kind: 'toggle', key: 'quick_scan_enabled', label: 'Enable Quick scan (watchlist priority)' },
      { id: 'dps', kind: 'num', key: 'dashboard_poll_sec', label: 'Dashboard live poll (seconds, 2–30)' },
      { id: 'wbi', kind: 'text', key: 'watchlist_bar_interval', autoCap: 'none' },
      { id: 'wbih', kind: 'hint', text: 'watchlist_bar_interval: 1d (default) | 1h | 15m — optional shorter bars for watchlist breakout only; daily 12-1 path unchanged.' },
      { id: 'oro', kind: 'toggle', key: 'options_read_only', label: 'Options research (read-only, no orders)' },
      { id: 'oroh', kind: 'hint', text: 'Phase 2 foothold: GET /options/{ticker} IV/nearest-expiry sketch. Never routes options orders.' },
      { id: 'poe', kind: 'toggle', key: 'paper_options_enabled', label: 'Paper options simulator (long call/put)' },
      { id: 'poeh', kind: 'hint', text: 'Educational paper options — firewall caps apply; never live options routing. origin=paper_options.' },
      { id: 'qen', kind: 'toggle', key: 'quotes_enabled', label: 'NBBO / top-of-book quotes (not L2 depth)' },
      { id: 'awl', kind: 'toggle', key: 'auto_web_learn_enabled', label: 'Scheduled allowlisted web learning' },
      { id: 'awlh', kind: 'hint', text: 'Periodic learn_from_web on macro + open/watchlist tickers → web_learning.jsonl. E-ve overnight research.' },
      { id: 'alen', kind: 'toggle', key: 'alerts_enabled', label: 'In-app / push alerts' },
      { id: 'alc', kind: 'toggle', key: 'alert_crash_mode', label: 'Alert: crash mode ON' },
      { id: 'alh', kind: 'toggle', key: 'alert_intraday_heat', label: 'Alert: intraday heat spike' },
      { id: 'als', kind: 'toggle', key: 'alert_strategy_cut', label: 'Alert: strategy cut on scoreboard' },
      { id: 'alf', kind: 'toggle', key: 'alert_firewall_deny_streak', label: 'Alert: firewall deny streak' },
      { id: 'mcp', kind: 'num', key: 'max_concurrent_positions', label: 'Max concurrent positions' },
      { id: 'mconf', kind: 'num', key: 'min_confidence', label: 'Min confidence to auto-enter (0–1)' },
      { id: 'mpp2', kind: 'num', key: 'max_position_pct', label: 'Max position weight of equity' },
      { id: 'mwe', kind: 'toggle', key: 'maintenance_windows_enabled', label: 'Maintenance windows (open/close buffer)' },
      { id: 'mob', kind: 'num', key: 'maintenance_open_buffer_minutes', label: 'Minutes after open to pause entries' },
      { id: 'mcb', kind: 'num', key: 'maintenance_close_buffer_minutes', label: 'Minutes before close to pause entries' },
      { id: 'cme', kind: 'toggle', key: 'crash_mode_enabled', label: 'Crash / regime-shock mode' },
      { id: 'clb', kind: 'num', key: 'crash_lookback', label: 'Crash lookback (days)' },
      { id: 'cth', kind: 'num', key: 'crash_threshold_pct', label: 'Crash threshold pct (e.g. -0.03)' },
      { id: 'cvm', kind: 'num', key: 'crash_vol_mult', label: 'Crash vol multiple vs baseline' },
      { id: 'ccd', kind: 'num', key: 'crash_cooldown_days', label: 'Crash cooldown (days)' },
      { id: 'csm', kind: 'num', key: 'crash_size_mult', label: 'Crash size mult for momentum/breakout' },
      { id: 'sbdw', kind: 'toggle', key: 'scoreboard_router_downweight', label: 'Scoreboard down-weight weak strategies' },
      { id: 'dae', kind: 'toggle', key: 'decision_audit_enabled', label: 'Decision audit trail (JSONL)' },
      { id: 'ast', kind: 'autoStatus' },
      { id: 'cbfalse', kind: 'btn', label: 'Circuit: mark false trip (loosen)', action: 'cbFalse', tone: 'locked' },
      { id: 'cbmiss', kind: 'btn', label: 'Circuit: mark missed bad (tighten)', action: 'cbMiss', tone: 'locked' },
      { id: 'cbres', kind: 'btn', label: 'Circuit: force resume', action: 'cbResume', tone: 'locked' },
    ];

    const stratRows: Row[] = [
      { id: 'strath', kind: 'hint', text: 'Router picks a subset by regime (auto) or runs all enabled (manual). Vol-target scales size only — not an entry signal. Pairs/FX/PEAD may no-op if data is thin.' },
      { id: 'rmodeh', kind: 'hint', text: 'router_mode: auto | manual' },
      { id: 'rmode', kind: 'text', key: 'router_mode', autoCap: 'none' },
      { id: 'vta', kind: 'num', key: 'vol_target_annual', label: 'Vol-target annual (e.g. 0.15 = 15%)' },
      { id: 'st_mom', kind: 'stratToggle', strategyId: 'momentum', label: 'Momentum (core)' },
      { id: 'st_mr', kind: 'stratToggle', strategyId: 'mean_reversion', label: 'Mean reversion' },
      { id: 'st_bo', kind: 'stratToggle', strategyId: 'breakout', label: 'Breakout' },
      { id: 'st_rs', kind: 'stratToggle', strategyId: 'relative_strength', label: 'Relative strength' },
      { id: 'st_vt', kind: 'stratToggle', strategyId: 'vol_target', label: 'Vol-target overlay' },
      { id: 'st_pairs', kind: 'stratToggle', strategyId: 'pairs', label: 'Pairs / relative value' },
      { id: 'st_fx', kind: 'stratToggle', strategyId: 'fx_mean_reversion', label: 'FX mean reversion (paper info)' },
      { id: 'st_pead', kind: 'stratToggle', strategyId: 'earnings_drift', label: 'Earnings drift (PEAD)' },
      { id: 'sthint', kind: 'stratHint' },
    ];

    const saveSec: Row[] = [
      { id: 'save', kind: 'btn', label: 'Save settings', action: 'save' },
    ];

    
    const brokerRows: Row[] = [
      { id: 'brh', kind: 'hint', text: 'Marketplace-lite: paper sim (default) · Alpaca paper · Alpaca live (locked) · IBKR coming soon. Live stays locked unless LIVE_TRADING_ENABLED=1.' },
      { id: 'brstatus', kind: 'hint', text: brokersCard
        ? `Default: ${brokersCard.default || 'paper_sim'} · live_enabled=${String(brokersCard.live_trading_enabled)} · keys=${String(brokersCard.alpaca_keys_detected)}`
        : (brokerStatus ? `live_enabled=${String(brokerStatus.live_trading_enabled)}` : 'Loading brokers…') },
      ...((brokersCard?.brokers || []).map((b: any) => ({
        id: `br_${b.id}`,
        kind: 'hint' as const,
        text: `${b.name}: ${b.status}${b.locked ? ' 🔒' : ''}${b.coming_soon ? ' (coming soon)' : ''} — ${String(b.note || '').slice(0, 100)}`,
      }))),
      { id: 'brtest', kind: 'btn', label: alpacaTestBusy ? 'Testing Alpaca…' : 'Test Alpaca connection (paper)', action: 'testAlpaca', tone: 'locked' },
      { id: 'bribkr', kind: 'hint', text: 'IBKR: planned stub + setup steps (TWS/Client Portal docs). Not wired for orders — does not block paper path.' },
    ];

    const packRows: Row[] = [
      { id: 'packh', kind: 'hint', text: 'Marketplace lite: one-tap packs with preview of toggles. Paper-first; does not unlock live.' },
      ...((packs || []).map((p: any) => ({
        id: `pack_${p.id}`,
        kind: 'btn' as const,
        label: packBusy === p.id ? `Applying ${p.name}…` : `Apply: ${p.name}`,
        action: `pack:${p.id}`,
        tone: 'accent' as const,
      }))),
      { id: 'packnote', kind: 'hint', text: (packs || []).map((p: any) =>
        `• ${p.name}: ${p.description}${p.beats_at ? ` — ${p.beats_at}` : ''}`
      ).join('\n') || 'Loading packs…' },
      { id: 'cov', kind: 'hint', text: coverage
        ? `Coverage: ${coverage.summary || ''} Options research=${coverage.options_read_only ? 'on' : 'off'}; trading still Phase 2.`
        : 'Coverage: equities + FX now; options research foothold optional.' },
    ];

return [
      { title: 'API server (your backend)', data: apiRows },
      { title: 'Remote access', data: remoteRows },
      { title: 'Install on your iPhone', data: installRows },
      { title: 'Paper vs Live (paper-first)', data: paperRows },
      { title: 'Broker connect', data: brokerRows },
      { title: 'Strategy packs (one-tap)', data: packRows },
      { title: 'Strategies / router', data: stratRows },
      { title: 'Auto learn / trade + data health', data: autoRows },
      { title: 'Momentum (seeded defaults)', data: momentum },
      { title: 'Advanced filters / exits', data: advanced },
      { title: 'Regime / ensemble / forward', data: regime },
      { title: 'News sentiment', data: news },
      { title: 'Time zone', data: tz },
      { title: 'Fees (paper realism)', data: fees },
      { title: 'Market data — free delayed vs SIP', data: data },
      { title: 'Live trading (personal risk toggle)', data: live },
      { title: 'Save', data: saveSec },
    ];
  }, [paperMode, sipEnabled, healthHint, apiSecured, remoteNoSecretWarn, ownerSecret, dataSourceStatus, liveUnlocked, brokerStatus, brokersCard, alpacaTestBusy, autoStatus, packs, coverage, packBusy, remoteEnabled, remoteUrl, remoteStatusHint]);

  const renderItem = useCallback(({ item }: { item: Row }) => {
    switch (item.kind) {
      case 'hint':
        return <Text style={styles.hint}>{item.text}</Text>;
      case 'warn':
        return <Text style={styles.warn}>{item.text}</Text>;
      case 'num':
        return (
          <View style={styles.field}>
            <Text style={styles.label}>{item.label}</Text>
            <TextInput
              style={styles.input}
              keyboardType="decimal-pad"
              value={cfg[item.key] != null ? String(cfg[item.key]) : ''}
              onChangeText={(t) => setNum(item.key, t)}
              placeholderTextColor={colors.muted}
            />
          </View>
        );
      case 'toggle':
        return (
          <View style={styles.switchRow}>
            <Text style={styles.label}>{item.label}</Text>
            <Switch
              value={!!cfg[item.key]}
              onValueChange={(v) => setToggle(item.key, v)}
              trackColor={{ true: colors.accent }}
              thumbColor={colors.white}
              ios_backgroundColor={colors.locked}
            />
          </View>
        );
      case 'text': {
        const defaults: Record<string, string> = {
          news_blend_mode: '70_30',
          commission_mode: 'per_share',
          user_timezone: 'America/Chicago',
          market_exchange: 'NYSE',
          router_mode: 'auto',
        };
        const raw = cfg[item.key];
        const val =
          raw != null && raw !== ''
            ? String(raw)
            : (defaults[item.key] ?? '');
        return (
          <TextInput
            style={styles.input}
            value={val}
            onChangeText={(t) => setText(item.key, t)}
            autoCapitalize={item.autoCap || 'none'}
            secureTextEntry={!!item.secure}
            placeholder={item.placeholder}
            placeholderTextColor={colors.muted}
          />
        );
      }
      case 'baseUrl':
        return (
          <TextInput
            style={styles.input}
            value={base}
            onChangeText={setBase}
            autoCapitalize="none"
            placeholderTextColor={colors.muted}
            keyboardType="url"
          />
        );
      case 'ownerSecret':
        return (
          <TextInput
            style={styles.input}
            value={ownerSecret}
            onChangeText={setOwnerSecretState}
            autoCapitalize="none"
            secureTextEntry
            placeholder="X-Owner-Secret (SecureStore)"
            placeholderTextColor={colors.muted}
          />
        );
      case 'remoteToggle':
        return (
          <View style={styles.switchRow}>
            <Text style={styles.label}>Use remote URL (when away from LAN)</Text>
            <Switch
              value={remoteEnabled}
              onValueChange={async (v) => {
                setRemoteEnabled(v);
                await setRemoteAccessEnabled(v);
                const effective = v && remoteUrl.trim() ? remoteUrl.trim() : base;
                setRemoteNoSecretWarn(!isLocalApiHost(effective) && !(ownerSecret || '').trim());
              }}
            />
          </View>
        );
      case 'remoteUrl':
        return (
          <TextInput
            style={styles.input}
            value={remoteUrl}
            onChangeText={setRemoteUrl}
            autoCapitalize="none"
            placeholder="http://100.x.y.z:8000"
            placeholderTextColor={colors.muted}
            keyboardType="url"
          />
        );
      case 'paperMode':
        return (
          <View style={styles.switchRow}>
            <Text style={styles.label}>Paper trading (your default — safe)</Text>
            <Switch
              value={paperMode}
              onValueChange={setPaperMode}
              trackColor={{ false: colors.locked, true: colors.good }}
              thumbColor={colors.white}
              ios_backgroundColor={colors.locked}
            />
          </View>
        );
      case 'sip':
        return (
          <View style={styles.switchRow}>
            <Text style={styles.label}>Real-time SIP (optional paid)</Text>
            <Switch
              value={sipEnabled}
              onValueChange={toggleSip}
              trackColor={{ true: colors.accent }}
              thumbColor={colors.white}
              ios_backgroundColor={colors.locked}
            />
          </View>
        );
      case 'dataStatus':
        if (!dataSourceStatus) return null;
        return (
          <Text style={styles.hint}>
            {dataSourceStatus.status_hint || `Active: ${String(dataSourceStatus.data_source)}`}
            {dataSourceStatus.fallback_active ? ' (fallback)' : ''}
            {` · keys ${dataSourceStatus.alpaca_keys_detected ? 'detected' : 'missing'}`}
            {dataSourceStatus.last_warning ? ` — ${dataSourceStatus.last_warning}` : ''}
            {'\n'}
            {(dataSourceStatus.enable_instructions || []).join('\n') ||
              'Enable: Alpaca Algo Trader Plus → set ALPACA keys → toggle SIP ON → check fallback_active=false.'}
          </Text>
        );
      case 'stratToggle': {
        const on = !!(cfg.strategy_enabled || {})[item.strategyId];
        return (
          <View style={styles.switchRow}>
            <Text style={styles.label}>{item.label}</Text>
            <Switch
              value={on}
              onValueChange={(v) => setStrategyToggle(item.strategyId, v)}
              trackColor={{ true: colors.accent }}
              thumbColor={colors.white}
              ios_backgroundColor={colors.locked}
            />
          </View>
        );
      }
      case 'stratHint': {
        const fired = autoStatus?.strategies_last_cycle?.fired || [];
        const mode = cfg.router_mode || autoStatus?.router_mode || 'auto';
        return (
          <Text style={styles.hint}>
            Router mode={String(mode)}. Last cycle fired:{' '}
            {fired.length ? fired.join(', ') : 'n/a (run a scan / auto-trade cycle)'}.
          </Text>
        );
      }
      case 'autoStatus': {
        const a = autoStatus || {};
        const cb = a.circuit_breaker || {};
        const lines = [
          `Loops: ${a.loops_started ? 'running' : 'stopped'} · learn=${String(a.auto_learn_enabled)} trade=${String(a.auto_trade_enabled)}`,
          `Last scan: ${a.last_scan_at || '—'} (${a.last_scan_count ?? '—'} sigs)`,
          `Last trade: ${a.last_trade_at || '—'}`,
          `Last learn: ${a.last_learn_at || '—'}`,
          `Circuit: ${cb.halted ? `HALTED — ${cb.reason || '?'}` : 'OK'}${cb.halted_since ? ` since ${cb.halted_since}` : ''}`,
        ];
        if (a.maintenance?.active) lines.push(`Maintenance: ${a.maintenance.reason}`);
        const cm = a.crash_mode || {};
        if (cm.active) {
          lines.push(`Crash mode: ON until ${cm.until || '—'}${cm.reason ? ` — ${String(cm.reason).slice(0, 60)}` : ''}`);
        } else {
          lines.push(`Crash mode: ${cm.enabled === false ? 'disabled' : 'OFF (armed)'}`);
        }
        return <Text style={styles.hint}>{lines.join(String.fromCharCode(10))}</Text>;
      }
      case 'installUrl':
        return (
          <View>
            <Text style={styles.label}>Install page URL (for QR)</Text>
            <TextInput
              style={styles.input}
              value={installPageUrl}
              onChangeText={setInstallPageUrl}
              autoCapitalize="none"
              placeholderTextColor={colors.muted}
            />
            <TouchableOpacity style={[styles.btn, styles.locked]} onPress={() => onAction('saveInstall')}>
              <Text style={styles.btnText}>Save install URL</Text>
            </TouchableOpacity>
          </View>
        );
      case 'btn': {
        const tone = item.tone || 'accent';
        const bg = tone === 'danger' ? styles.btnDanger : tone === 'locked' ? styles.locked : null;
        return (
          <TouchableOpacity style={[styles.btn, bg]} onPress={() => onAction(item.action)}>
            <Text style={styles.btnText}>{item.label}</Text>
          </TouchableOpacity>
        );
      }
      case 'liveBlock':
        if (!liveUnlocked) {
          return (
            <TouchableOpacity style={[styles.btn, styles.locked]} onPress={() => onAction('unlockLive')}>
              <Text style={styles.btnText}>Unlock Live Trading UI…</Text>
            </TouchableOpacity>
          );
        }
        return (
          <View>
            <Text style={styles.label}>Alpaca API Key</Text>
            <TextInput
              style={styles.input}
              value={apiKey}
              onChangeText={setApiKey}
              autoCapitalize="none"
              secureTextEntry
              placeholderTextColor={colors.muted}
            />
            <Text style={styles.label}>Alpaca API Secret</Text>
            <TextInput
              style={styles.input}
              value={apiSecret}
              onChangeText={setApiSecret}
              autoCapitalize="none"
              secureTextEntry
              placeholderTextColor={colors.muted}
            />
            <TouchableOpacity style={styles.btn} onPress={() => onAction('saveKeys')}>
              <Text style={styles.btnText}>Save keys to SecureStore</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.btn, styles.btnDanger]} onPress={() => onAction('kill')}>
              <Text style={styles.btnText}>KILL SWITCH</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.btn, styles.locked]} onPress={() => onAction('lockLive')}>
              <Text style={styles.btnText}>Lock & clear keys</Text>
            </TouchableOpacity>
            {brokerStatus ? (
              <Text style={styles.hint}>Server live enabled: {String(brokerStatus.live_trading_enabled)}</Text>
            ) : null}
          </View>
        );
      default:
        return null;
    }
  }, [
    cfg, base, ownerSecret, apiSecured, remoteNoSecretWarn, healthHint, paperMode, sipEnabled, dataSourceStatus, installPageUrl, autoStatus,
    liveUnlocked, apiKey, apiSecret, brokerStatus, setNum, setToggle, setStrategyToggle, setText, toggleSip, onAction,
    remoteEnabled, remoteUrl,
  ]);

  const keyExtractor = useCallback((item: Row) => item.id, []);
  const renderSectionHeader = useCallback(
    ({ section }: { section: { title: string } }) => <SectionHeader title={section.title} />,
    [],
  );

  return (
    <View style={styles.container}>
      <SectionList
        sections={sections}
        keyExtractor={keyExtractor}
        renderItem={renderItem}
        renderSectionHeader={renderSectionHeader}
        stickySectionHeadersEnabled={false}
        initialNumToRender={16}
        maxToRenderPerBatch={12}
        windowSize={10}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingHorizontal: space.md, paddingTop: space.sm, paddingBottom: space.xxxl }}
        ListHeaderComponent={<Text style={styles.title}>Settings</Text>}
      />
      <InstallQrModal
        visible={installOpen}
        url={installPageUrl}
        onChangeUrl={setInstallPageUrl}
        onClose={() => setInstallOpen(false)}
        onSaveUrl={saveInstallUrl}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  title: { ...type.title, color: colors.text, marginBottom: space.sm },
  section: {
    ...type.section,
    color: colors.accent,
    textTransform: 'uppercase',
    marginTop: space.xl,
    marginBottom: space.sm,
    backgroundColor: colors.bg,
    paddingVertical: 4,
  },
  hint: { color: colors.muted, marginBottom: space.sm, fontSize: 12, lineHeight: 17 },
  warn: { color: colors.warn, marginBottom: space.sm, fontSize: 12, lineHeight: 17 },
  field: { marginBottom: space.sm + 2 },
  label: { color: colors.muted, marginBottom: 4, fontSize: 13, flex: 1, marginRight: 8 },
  input: {
    backgroundColor: colors.card, color: colors.text, padding: space.md,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, marginBottom: space.sm,
  },
  switchRow: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    marginBottom: space.sm + 2, paddingVertical: 2,
  },
  btn: {
    backgroundColor: colors.accent, padding: 14, borderRadius: radius.md,
    alignItems: 'center', marginTop: space.sm + 2, marginBottom: 2,
  },
  locked: { backgroundColor: colors.locked },
  btnDanger: { backgroundColor: colors.bad },
  btnText: { color: colors.white, fontWeight: '700' },
});
