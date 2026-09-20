import { useEffect, useState } from 'react';
import * as Notifications from 'expo-notifications';
import { api } from '../api/client';

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

export function useNotifications() {
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const { status: existing } = await Notifications.getPermissionsAsync();
        let finalStatus = existing;
        if (existing !== 'granted') {
          const { status } = await Notifications.requestPermissionsAsync();
          finalStatus = status;
        }
        if (finalStatus !== 'granted') return;
        const t = (await Notifications.getExpoPushTokenAsync()).data;
        setToken(t);
        await api.registerPush(t);
      } catch (e) {
        console.warn('Push setup skipped:', e);
      }
    })();
  }, []);

  return token;
}
