/**
 * Broker + market-data API keys — NEVER plain text in AsyncStorage/files.
 * Uses expo-secure-store (iOS Keychain / Android Keystore).
 *
 * Alpaca trading and SIP market data share the same API key/secret.
 * Algo Trader Plus (~$99/mo) is required for wss SIP real-time feeds.
 */
import * as SecureStore from 'expo-secure-store';

const KEY_ID = 'broker.alpaca.apiKey';
const KEY_SECRET = 'broker.alpaca.apiSecret';
const KEY_LIVE_UNLOCK = 'broker.liveUnlocked'; // user explicitly enabled UI
const KEY_SIP_PREF = 'data.realtimeSipEnabled'; // local UI preference mirror

export async function saveAlpacaKeys(apiKey: string, apiSecret: string): Promise<void> {
  await SecureStore.setItemAsync(KEY_ID, apiKey);
  await SecureStore.setItemAsync(KEY_SECRET, apiSecret);
}

export async function loadAlpacaKeys(): Promise<{ apiKey: string; apiSecret: string } | null> {
  const apiKey = await SecureStore.getItemAsync(KEY_ID);
  const apiSecret = await SecureStore.getItemAsync(KEY_SECRET);
  if (!apiKey || !apiSecret) return null;
  return { apiKey, apiSecret };
}

export async function clearAlpacaKeys(): Promise<void> {
  await SecureStore.deleteItemAsync(KEY_ID);
  await SecureStore.deleteItemAsync(KEY_SECRET);
}

/** Alias — SIP uses the same SecureStore keys as brokerage. */
export const saveAlpacaDataKeys = saveAlpacaKeys;
export const loadAlpacaDataKeys = loadAlpacaKeys;
export const clearAlpacaDataKeys = clearAlpacaKeys;

export async function setLiveUnlocked(unlocked: boolean): Promise<void> {
  await SecureStore.setItemAsync(KEY_LIVE_UNLOCK, unlocked ? '1' : '0');
}

export async function isLiveUnlocked(): Promise<boolean> {
  return (await SecureStore.getItemAsync(KEY_LIVE_UNLOCK)) === '1';
}

export async function setSipPrefLocal(enabled: boolean): Promise<void> {
  await SecureStore.setItemAsync(KEY_SIP_PREF, enabled ? '1' : '0');
}

export async function getSipPrefLocal(): Promise<boolean> {
  return (await SecureStore.getItemAsync(KEY_SIP_PREF)) === '1';
}
