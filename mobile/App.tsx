import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer, DarkTheme } from '@react-navigation/native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { enableScreens, enableFreeze } from 'react-native-screens';
import { RootTabs } from './src/navigation/RootTabs';
import { colors } from './src/theme/tokens';

enableScreens(true);
enableFreeze(true);

const theme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: colors.bg,
    card: colors.card,
    text: colors.text,
    border: colors.border,
    primary: colors.accent,
    notification: colors.accent,
  },
};

export default function App() {
  return (
    <SafeAreaProvider>
      <NavigationContainer theme={theme}>
        <StatusBar style="light" />
        <RootTabs />
      </NavigationContainer>
    </SafeAreaProvider>
  );
}
