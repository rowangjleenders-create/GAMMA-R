// Lightweight key-value: memory + SecureStore when available (prefs + secrets).

const mem = new Map<string, string>();

async function secureGet(key: string): Promise<string | null> {
  try {
    const SecureStore = require('expo-secure-store');
    return await SecureStore.getItemAsync(key);
  } catch {
    return mem.get(key) ?? null;
  }
}

async function secureSet(key: string, value: string): Promise<void> {
  mem.set(key, value);
  try {
    const SecureStore = require('expo-secure-store');
    await SecureStore.setItemAsync(key, value);
  } catch {
    /* memory only */
  }
}

async function secureDel(key: string): Promise<void> {
  mem.delete(key);
  try {
    const SecureStore = require('expo-secure-store');
    await SecureStore.deleteItemAsync(key);
  } catch {
    /* ignore */
  }
}

const AsyncStorage = {
  getItem: async (k: string) => mem.get(k) ?? (await secureGet(k)),
  setItem: async (k: string, v: string) => {
    await secureSet(k, v);
  },
  removeItem: async (k: string) => {
    await secureDel(k);
  },
};

export default AsyncStorage;
