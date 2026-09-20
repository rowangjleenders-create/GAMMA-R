import React, { useCallback, useRef, useState } from 'react';
import {
  View, Text, ScrollView, StyleSheet, RefreshControl, Alert, ActivityIndicator, TextInput,
} from 'react-native';
import { api } from '../api/client';
import { colors, space, radius, type } from '../theme/tokens';
import { useSilentRefresh } from '../hooks/useSilentRefresh';
import { EmptyView, ErrorBanner } from '../components/StatusViews';
import { SkeletonList } from '../components/Skeleton';
import { Card, Title, Muted, SectionLabel, PrimaryButton } from '../components/ui';
import { Sparkline } from '../components/Sparkline';

export function LearningScreen() {
  const [stats, setStats] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [strategiesHint, setStrategiesHint] = useState<string | null>(null);
  const [scoreboard, setScoreboard] = useState<any | null>(null);
  const [auditRows, setAuditRows] = useState<any[]>([]);
  const [importCsv, setImportCsv] = useState('');
  const [importPreview, setImportPreview] = useState<any | null>(null);
  const [lastImport, setLastImport] = useState<any | null>(null);
  const [originStats, setOriginStats] = useState<any | null>(null);
  const [importAvailable, setImportAvailable] = useState(true);
  const [paperReport, setPaperReport] = useState<any | null>(null);
  const [leaderboard, setLeaderboard] = useState<any | null>(null);
  const hasData = useRef(false);

  const load = useCallback(async (opts: { silent?: boolean }, signal: AbortSignal) => {
    if (!opts.silent) {
      setRefreshing(true);
      setError(null);
    }
    try {
      const [s, h] = await Promise.all([api.learningStats(), api.learningHistory()]);
      if (signal.aborted) return;
      setStats(s);
      setHistory(h.adjustments || []);
      hasData.current = true;
      setError(null);
      try {
        const a = await api.autoStatus();
        if (!signal.aborted) {
          const fired = a?.strategies_last_cycle?.fired || [];
          const regime = a?.router?.regime_label;
          const crash = a?.crash_mode;
          const crashBit = crash?.active
            ? ` · Crash mode ON until ${crash.until || '?'}`
            : '';
          setStrategiesHint(
            fired.length
              ? `Last strategies: ${fired.join(', ')}${regime ? ` (regime ${regime})` : ''}${crashBit}`
              : `Router ${a?.router_mode || 'auto'} — no multi-strategy cycle yet${crashBit}`,
          );
        }
      } catch { /* optional */ }
      try {
        const sb = await api.strategiesScoreboard();
        if (!signal.aborted) setScoreboard(sb);
      } catch { /* optional */ }
      try {
        const au = await api.auditDecisions(12);
        if (!signal.aborted) setAuditRows(au?.decisions || []);
      } catch { /* optional */ }
      try {
        const ls = await api.tradesLearningStats();
        if (!signal.aborted) {
          setOriginStats(ls);
          setImportAvailable(true);
          setLastImport(ls?.external?.last_import || ls?.last_import || null);
        }
      } catch {
        if (!signal.aborted) setImportAvailable(false);
      }
      try {
        const ext = await api.tradesExternal(5);
        if (!signal.aborted && ext?.last_import) setLastImport(ext.last_import);
      } catch { /* optional */ }
      try {
        const pr = await api.paperReport('json');
        if (!signal.aborted) setPaperReport(pr);
      } catch { /* optional */ }
      try {
        const lb = await api.paperLeaderboard(12);
        if (!signal.aborted) setLeaderboard(lb);
      } catch { /* optional */ }
    } catch (e: any) {
      if (e?.name === 'AbortError' || signal.aborted) return;
      if (!opts.silent || !hasData.current) setError(e.message || String(e));
    } finally {
      if (!signal.aborted) {
        setRefreshing(false);
        setLoading(false);
      }
    }
  }, []);

  const { refresh } = useSilentRefresh(load, { intervalMs: 90_000 });


  const dryRunImport = async () => {
    if (!importCsv.trim()) {
      Alert.alert('Paste CSV', 'Paste brokerage CSV (headers: symbol, side, qty, price, datetime).');
      return;
    }
    setBusy('import-preview');
    try {
      const r = await api.tradesImport('csv', importCsv, true);
      setImportPreview(r);
      Alert.alert(
        'Dry-run preview',
        [
          `Parsed fills: ${r.parsed ?? 0}`,
          `New fills: ${r.new_fills ?? r.would_import ?? 0}`,
          `Dupes skipped: ${r.duplicate_fills ?? r.duplicates ?? 0}`,
          `Closed round-trips: ${r.closed_round_trips ?? r.would_import ?? 0}`,
          `Would journal: ${r.journaled ?? r.would_import ?? 0}`,
          '',
          'Confirm import to save. Does not place live orders.',
        ].join('\n'),
      );
    } catch (e: any) {
      setImportAvailable(false);
      Alert.alert('Import unavailable', e?.message || String(e));
    } finally {
      setBusy(null);
    }
  };

  const confirmImport = async () => {
    if (!importCsv.trim()) {
      Alert.alert('Paste CSV', 'Paste CSV first, then dry-run, then confirm.');
      return;
    }
    Alert.alert(
      'Confirm import?',
      'Journals external closes for learning. Paper cash unchanged. No live trading.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Import',
          onPress: async () => {
            setBusy('import');
            try {
              const r = await api.tradesImport('csv', importCsv, false);
              setLastImport(r);
              setImportPreview(null);
              setImportCsv('');
              Alert.alert(
                'Imported',
                `Journaled ${r.journaled ?? r.imported ?? 0} closes · ${r.new_fills ?? r.imported ?? 0} fills · dupes ${r.duplicate_fills ?? r.duplicates ?? 0}`,
              );
              refresh();
            } catch (e: any) {
              Alert.alert('Import failed', e?.message || String(e));
            } finally {
              setBusy(null);
            }
          },
        },
      ],
    );
  };

  const exportPaperReport = async () => {
    setBusy('export');
    try {
      const report = await api.paperReport('json');
      const summary = report?.summary || {};
      const vs = summary.vs_buy_hold || {};
      Alert.alert(
        'PAPER report',
        [
          `Label: ${report?.label || 'PAPER / not live audited'}`,
          `Return: ${summary.return_pct != null ? (Number(summary.return_pct) * 100).toFixed(2) + '%' : '—'}`,
          `Max DD: ${summary.max_drawdown_pct != null ? (Number(summary.max_drawdown_pct) * 100).toFixed(2) + '%' : '—'}`,
          `Win rate: ${summary.win_rate != null ? (Number(summary.win_rate) * 100).toFixed(1) + '%' : '—'}`,
          `Trades: ${summary.closed_trades ?? '—'}`,
          `vs buy-hold: ${vs.available ? ((Number(vs.return_pct) || 0) * 100).toFixed(2) + '%' : (vs.note || 'n/a')}`,
          '',
          'Not live audited. Also GET /paper/report',
        ].join('\n'),
      );
    } catch (e: any) {
      Alert.alert('Export failed', e?.message || String(e));
    } finally {
      setBusy(null);
    }
  };

  const run = async () => {
    setBusy('run');
    try {
      const r = await api.learningRun();
      Alert.alert(
        'Learning',
        r.ran ? `Applied ${r.adjustments?.length || 0} adjustments` : r.reason || 'No changes',
      );
      refresh();
    } catch (e: any) {
      Alert.alert('Error', e.message);
    } finally {
      setBusy(null);
    }
  };

  const replay = async () => {
    setBusy('replay');
    try {
      const r = await api.learningReplay(5);
      Alert.alert(
        'Session replay',
        r.verdict || JSON.stringify(r).slice(0, 280),
      );
    } catch (e: any) {
      Alert.alert('Replay failed', e.message);
    } finally {
      setBusy(null);
    }
  };

  const reset = () => {
    Alert.alert('Reset to day-one SEED?', 'Restores lookback=10, vol 1.5x, top 10%, SL 5%, TP 15%.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Reset',
        style: 'destructive',
        onPress: async () => {
          setBusy('reset');
          try {
            await api.learningReset(false);
            refresh();
          } catch (e: any) {
            Alert.alert('Reset failed', e.message);
          } finally {
            setBusy(null);
          }
        },
      },
    ]);
  };

  const histTrain = () => {
    Alert.alert('Historical train', 'Default 20 years (slow). Continue?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Run 20y',
        onPress: async () => {
          setBusy('train');
          Alert.alert('Started', 'This can take a while — check API logs.');
          try {
            await api.historicalTrain(20);
            refresh();
          } catch (e: any) {
            Alert.alert('Train failed', e.message);
          } finally {
            setBusy(null);
          }
        },
      },
    ]);
  };

  if (loading && !stats) {
    return (
      <View style={styles.container}>
        <SkeletonList rows={6} rowHeight={64} />
      </View>
    );
  }

  if (!stats) {
    return (
      <View style={styles.container}>
        {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}
        <EmptyView
          title="Learning unavailable"
          hint="Start the API server and retry."
          actionLabel="Retry"
          onAction={refresh}
        />
      </View>
    );
  }

  const baseline = stats.day_one_baseline?.params || {};
  const evolved = stats.evolved_vs_baseline || {};

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={{ paddingHorizontal: space.md, paddingTop: space.sm, paddingBottom: space.xxxl }}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />
      }
    >
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}
      <Title>Learning / Performance</Title>
      {strategiesHint ? <Muted>{strategiesHint}</Muted> : null}

      <SectionLabel>Day one baseline (SEED)</SectionLabel>
      <Muted>{stats.day_one_baseline?.description}</Muted>
      <Card>
        <Text style={styles.mono}>
          lookback={baseline.lookback_days} · vol×{baseline.volume_multiple} · top{' '}
          {(baseline.top_pct || 0) * 100}% · SL {(baseline.stop_loss_pct || 0) * 100}% · TP{' '}
          {(baseline.take_profit_pct || 0) * 100}%
        </Text>
      </Card>

      <SectionLabel>Evolved vs baseline</SectionLabel>
      <Card>
        {Object.keys(evolved).length === 0 ? (
          <Muted>No param snapshot yet.</Muted>
        ) : (
          Object.entries(evolved).slice(0, 12).map(([k, v]: any) => (
            <Text key={k} style={styles.row}>
              {k}: {String(v.day_one)} → {String(v.current)}
              {v.changed_from_seed ? ' ★' : ''}
            </Text>
          ))
        )}
      </Card>

      <SectionLabel>Historical baseline</SectionLabel>
      <Muted>
        {stats.historical_baseline?.present
          ? `Present (${stats.historical_baseline.years || '?'}y)`
          : 'Not trained yet — run historical train (default 20y)'}
      </Muted>
      {(stats.historical_baseline?.era_performance || []).slice(0, 3).map((e: any, i: number) => (
        <Text key={i} style={styles.row}>
          Era {e.test_start}: {e.regime?.trend}/{e.regime?.vol} ret={((e.best_return || 0) * 100).toFixed(1)}%
        </Text>
      ))}

      <SectionLabel>Fee impact</SectionLabel>
      <Card>
        <Text style={styles.row}>
          {(stats.fee_settings?.fees_enabled ?? true) ? 'Fees ON' : 'Fees OFF'}
          {' · '}mode {stats.fee_settings?.commission_mode ?? 'per_share'}
          {' · '}slip {(((stats.fee_settings?.slippage_pct ?? 0.001) as number) * 100).toFixed(2)}%
        </Text>
        <Text style={styles.row}>
          Total fees ${(stats.total_fees_paid ?? stats.fee_impact?.total_fees_paid ?? 0).toFixed(2)}
        </Text>
        <Text style={styles.row}>
          Gross → Net:{' '}
          {stats.gross_return_pct != null || stats.fee_impact?.gross_return_pct != null
            ? `${(((stats.gross_return_pct ?? stats.fee_impact?.gross_return_pct) as number) * 100).toFixed(2)}%`
            : '—'}
          {' → '}
          {stats.net_return_pct != null || stats.fee_impact?.net_return_pct != null
            ? `${(((stats.net_return_pct ?? stats.fee_impact?.net_return_pct) as number) * 100).toFixed(2)}%`
            : '—'}
        </Text>
      </Card>

      <SectionLabel>PAPER track record (not live audited)</SectionLabel>
      <Muted>Simulated fills — not live audited. Export for full curve / CSV.</Muted>
      {leaderboard ? (
        <Card style={{ marginBottom: space.md }}>
          <Title>PAPER leaderboard</Title>
          <Muted>{leaderboard.watermark || 'PAPER — not live audited'}</Muted>
          <Muted>
            {(leaderboard.ranks || []).slice(0, 3).map((r: any) =>
              `${r.name || r.strategy_id} (n=${r.sample_size || 0})`
            ).join(' · ') || 'No ranked strategies yet'}
          </Muted>
          <Muted>Share: /paper/leaderboard.html on your API host</Muted>
        </Card>
      ) : null}
      {paperReport ? (
        <Card>
          <Text style={styles.row}>
            Return{' '}
            {paperReport.summary?.return_pct != null
              ? `${(Number(paperReport.summary.return_pct) * 100).toFixed(2)}%`
              : '—'}
            {' · '}Max DD{' '}
            {paperReport.summary?.max_drawdown_pct != null
              ? `${(Number(paperReport.summary.max_drawdown_pct) * 100).toFixed(2)}%`
              : '—'}
            {' · '}WR{' '}
            {paperReport.summary?.win_rate != null
              ? `${(Number(paperReport.summary.win_rate) * 100).toFixed(1)}%`
              : '—'}
          </Text>
          <Text style={styles.meta}>
            Equity curve points: {paperReport.summary?.equity_curve_points ?? (paperReport.equity_curve || []).length}
            {' · '}Months: {(paperReport.monthly_returns || []).length}
            {' · '}Underwater: {(paperReport.underwater_periods || []).length}
          </Text>
          {(paperReport.equity_sparkline || []).length >= 2 ? (
            <View style={{ marginTop: 8 }}>
              <Sparkline points={paperReport.equity_sparkline} width={280} height={40} />
            </View>
          ) : (
            <Muted>No sparkline yet — close paper trades to build the curve.</Muted>
          )}
          {(paperReport.monthly_returns || []).length > 0 ? (
            <View style={{ marginTop: 8 }}>
              <Text style={styles.meta}>Monthly returns (last 6)</Text>
              {(paperReport.monthly_returns || []).slice(-6).map((m: any) => (
                <Text key={m.month} style={styles.row}>
                  {m.month}: {m.return_pct != null ? `${(Number(m.return_pct) * 100).toFixed(2)}%` : '—'}
                  {' · '}${Number(m.end_equity || 0).toFixed(0)}
                </Text>
              ))}
            </View>
          ) : null}
          {(paperReport.strategy_attribution || []).length > 0 ? (
            <View style={{ marginTop: 8 }}>
              <Text style={styles.meta}>Strategy attribution</Text>
              {(paperReport.strategy_attribution || []).slice(0, 5).map((a: any) => (
                <Text key={a.strategy_id} style={styles.row}>
                  {a.strategy_id}: PnL ${Number(a.total_pnl || 0).toFixed(2)}
                  {a.win_rate != null ? ` · WR ${(Number(a.win_rate) * 100).toFixed(0)}%` : ''}
                  {' · '}n={a.trades}
                </Text>
              ))}
            </View>
          ) : null}
          {paperReport.summary?.vs_buy_hold?.available ? (
            <Text style={styles.meta}>
              vs SPY buy-hold: {(Number(paperReport.summary.vs_buy_hold.return_pct) * 100).toFixed(2)}%
              {' · '}{paperReport.summary.vs_buy_hold.note || ''}
            </Text>
          ) : (
            <Text style={styles.meta}>
              vs SPY: {paperReport.summary?.vs_buy_hold?.note || 'n/a'}
            </Text>
          )}
        </Card>
      ) : (
        <Card><Muted>PAPER report loading…</Muted></Card>
      )}

      <SectionLabel>PAPER scoreboard (not live audited)</SectionLabel>
      <Muted>
        {scoreboard?.label || 'Rolling PAPER journal — keep / watch / cut · not live audited'}
      </Muted>
      {(scoreboard?.strategies || []).length === 0 ? (
        <Card><Muted>No scored strategies yet — close paper trades tagged with strategy_id.</Muted></Card>
      ) : (
        (scoreboard?.strategies || []).slice(0, 10).map((s: any) => {
          const p = s.primary || {};
          const tone =
            s.status === 'keep' ? colors.good
            : s.status === 'cut' ? colors.bad
            : colors.warn || colors.muted;
          return (
            <Card key={s.strategy_id}>
              <Text style={styles.row}>
                <Text style={{ color: tone, fontWeight: '700' }}>{String(s.status || '').toUpperCase()}</Text>
                {'  '}{s.name || s.strategy_id}
                {' · '}n={s.sample_size}
                {p.expectancy != null ? ` · E[pnl]=${Number(p.expectancy).toFixed(2)}` : ''}
                {p.win_rate != null ? ` · WR ${(Number(p.win_rate) * 100).toFixed(0)}%` : ''}
                {p.profit_factor != null ? ` · PF ${Number(p.profit_factor).toFixed(2)}` : ''}
              </Text>
            </Card>
          );
        })
      )}

      <SectionLabel>Recent decisions (audit)</SectionLabel>
      {auditRows.length === 0 ? (
        <Card><Muted>No decision audit rows yet — run auto-trade or paper a fill.</Muted></Card>
      ) : (
        auditRows.slice(0, 8).map((d: any, i: number) => (
          <Card key={`${d.timestamp || i}-${d.ticker || i}`}>
            <Text style={styles.meta}>{d.timestamp} · {d.source || '?'} · {d.ticker || '—'}</Text>
            <Text style={styles.row}>
              {d.strategy_id || '—'}
              {d.order_id ? ` · order ${d.order_id}` : ''}
              {d.skip_reason ? ` · skip: ${String(d.skip_reason).slice(0, 80)}` : ''}
              {d.firewall_allow === false ? ` · FW DENY: ${d.firewall_reason || ''}` : ''}
              {d.firewall_allow === true ? ' · FW allow' : ''}
            </Text>
          </Card>
        ))
      )}

      {importAvailable ? (
        <>
          <SectionLabel>Import outside trades</SectionLabel>
          <Muted>
            Paste brokerage CSV (symbol/ticker, side, qty, price, datetime). Dry-run previews counts;
            confirm journals for learning only — never auto live trades. Paper portfolio cash stays separate.
          </Muted>
          <Card>
            <TextInput
              style={styles.csvInput}
              multiline
              placeholder={"symbol,side,qty,price,datetime\nAAPL,buy,10,190.5,2026-09-01T14:30:00Z\nAAPL,sell,10,195.0,2026-09-05T15:00:00Z"}
              placeholderTextColor={colors.muted}
              value={importCsv}
              onChangeText={setImportCsv}
              autoCapitalize="none"
              autoCorrect={false}
            />
            {importPreview ? (
              <Text style={styles.row}>
                Preview: {importPreview.parsed ?? 0} parsed · {importPreview.closed_round_trips ?? importPreview.would_import ?? 0} closes ·{' '}
                {importPreview.journaled ?? importPreview.would_import ?? 0} to journal
              </Text>
            ) : null}
            {originStats ? (
              <Text style={styles.meta}>
                Learning samples — paper {originStats.paper?.count ?? 0} · external {originStats.external?.count ?? 0} ·
                combined {originStats.combined?.count ?? 0}
                {originStats.combined?.win_rate != null
                  ? ` · combined WR ${(Number(originStats.combined.win_rate) * 100).toFixed(1)}%`
                  : ''}
              </Text>
            ) : null}
            {lastImport ? (
              <Text style={styles.meta}>
                Last import: journaled {lastImport.journaled ?? lastImport.imported ?? '—'} · fills {lastImport.new_fills ?? lastImport.imported ?? '—'} ·{' '}
                {lastImport.at || lastImport.updated_at || ''}
              </Text>
            ) : (
              <Muted>No external import yet.</Muted>
            )}
          </Card>
          <PrimaryButton label="Dry-run preview" onPress={dryRunImport} tone="alt" disabled={!!busy} />
          <PrimaryButton label="Confirm import" onPress={confirmImport} disabled={!!busy} />
        </>
      ) : (
        <>
          <SectionLabel>Import outside trades</SectionLabel>
          <Card>
            <Muted>External import API not detected on this server (feature-detect). Update API and retry.</Muted>
          </Card>
        </>
      )}

      <SectionLabel>Overnight web → learning</SectionLabel>
      <Card>
        {(stats.overnight_web?.present || (stats.overnight_web?.note_count ?? 0) > 0) ? (
          <>
            <Text style={styles.row}>
              Notes {stats.overnight_web?.note_count ?? 0}
              {stats.overnight_web?.updated_at ? ` · ${String(stats.overnight_web.updated_at).slice(0, 19)}` : ''}
            </Text>
            <Muted>{stats.overnight_web?.label || 'Allowlisted overnight research distilled into learning summary (educational).'}</Muted>
            {(stats.overnight_web?.topics || []).slice(0, 6).map((topic: string) => (
              <Text key={topic} style={styles.meta}>· {topic}</Text>
            ))}
          </>
        ) : (
          <Muted>
            No overnight web digest yet. Enable scheduled web learn or POST /edge/overnight/ingest — educational only.
          </Muted>
        )}
      </Card>

      <SectionLabel>Live journal</SectionLabel>
      {(stats.journal_count ?? 0) === 0 ? (
        <Card>
          <Muted>No closed trades yet. Paper fills or Import outside trades, then run learning.</Muted>
        </Card>
      ) : (
        <Text style={styles.row}>
          Trades {stats.journal_count} · Win rate {((stats.win_rate || 0) * 100).toFixed(1)}% · Unlearned{' '}
          {stats.unlearned}
        </Text>
      )}

      <SectionLabel>Recent adjustments</SectionLabel>
      {history.length === 0 ? (
        <Muted>No adjustments yet — close paper trades then run learning.</Muted>
      ) : (
        history.slice(-5).reverse().map((b, i) => (
          <Card key={i}>
            <Text style={styles.meta}>{b.at} · {b.trigger}</Text>
            {(b.adjustments || []).map((a: any, j: number) => (
              <Text key={j} style={styles.row}>
                {a.param}: {String(a.before)} → {String(a.after)} — {a.why}
              </Text>
            ))}
          </Card>
        ))
      )}

      {busy ? (
        <View style={styles.busyRow}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.meta}>Working ({busy})…</Text>
        </View>
      ) : null}

      <PrimaryButton label="Export PAPER report" onPress={exportPaperReport} tone="alt" disabled={!!busy} />
      <PrimaryButton label="Run learning now" onPress={run} disabled={!!busy} />
      <PrimaryButton label={busy === 'replay' ? 'Replaying…' : 'Replay last sessions vs learned'} onPress={replay} tone="alt" disabled={!!busy} />
      <PrimaryButton label="Historical train (20y)" onPress={histTrain} tone="alt" disabled={!!busy} />
      <PrimaryButton label="Reset to day-one SEED" onPress={reset} tone="danger" disabled={!!busy} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  mono: { color: colors.text, fontFamily: 'monospace', fontSize: 13, lineHeight: 20 },
  row: { color: colors.text, marginBottom: 4, fontSize: 14 },
  meta: { color: colors.muted, marginBottom: 4, fontSize: 12 },
  busyRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: space.md },
  csvInput: {
    minHeight: 96,
    maxHeight: 180,
    color: colors.text,
    fontFamily: 'monospace',
    fontSize: 12,
    borderWidth: 1,
    borderColor: colors.border || '#333',
    borderRadius: radius.md || 8,
    padding: space.sm,
    marginBottom: space.sm,
    textAlignVertical: 'top',
  },
});
