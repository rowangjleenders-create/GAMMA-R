import React, { memo, useMemo } from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { Text, View, StyleSheet, Platform } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { DashboardScreen } from '../screens/DashboardScreen';
import { SignalDetailScreen } from '../screens/SignalDetailScreen';
import { PortfolioScreen } from '../screens/PortfolioScreen';
import { WatchlistScreen } from '../screens/WatchlistScreen';
import { LearningScreen } from '../screens/LearningScreen';
import { SettingsScreen } from '../screens/SettingsScreen';
import { CoPilotScreen } from '../screens/CoPilotScreen';
import { ScannerScreen } from '../screens/ScannerScreen';
import { ProDeskScreen } from '../screens/ProDeskScreen';
import { colors, type } from '../theme/tokens';

const Tab = createBottomTabNavigator();
const Stack = createNativeStackNavigator();

const stackScreenOptions = {
  headerStyle: { backgroundColor: colors.card },
  headerTintColor: colors.text,
  headerTitleStyle: { fontWeight: '700' as const, fontSize: 17 },
  headerTitleAlign: 'center' as const,
  headerBackTitleVisible: false,
  headerShadowVisible: false,
  contentStyle: { backgroundColor: colors.bg },
  animation: 'slide_from_right' as const,
  freezeOnBlur: true,
};

function DashStack() {
  return (
    <Stack.Navigator screenOptions={stackScreenOptions}>
      <Stack.Screen name="Signals" component={DashboardScreen} options={{ title: 'GAMMA-R' }} />
      <Stack.Screen name="SignalDetail" component={SignalDetailScreen} options={{ title: 'Signal' }} />
      <Stack.Screen name="Scanner" component={ScannerScreen} options={{ title: 'Pro scanner' }} />
      <Stack.Screen name="ProDesk" component={ProDeskScreen} options={{ title: 'Pro Desk' }} />
    </Stack.Navigator>
  );
}

const TabIcon = memo(function TabIcon({
  glyph,
  label,
  focused,
}: {
  glyph: string;
  label: string;
  focused: boolean;
}) {
  return (
    <View style={styles.tabIcon}>
      <Text style={{ fontSize: 15, opacity: focused ? 1 : 0.5 }}>{glyph}</Text>
      <Text style={[styles.tabLabel, { color: focused ? colors.accent : colors.muted }]}>{label}</Text>
    </View>
  );
});

export function RootTabs() {
  const insets = useSafeAreaInsets();
  const bottomPad = Math.max(insets.bottom, Platform.OS === 'ios' ? 8 : 6);
  const tabBarHeight = 50 + bottomPad;

  const screenOptions = useMemo(
    () => ({
      headerStyle: { backgroundColor: colors.card },
      headerTintColor: colors.text,
      headerTitleStyle: { fontWeight: '700' as const, fontSize: 17 },
      headerTitleAlign: 'center' as const,
      headerShadowVisible: false,
      tabBarStyle: {
        backgroundColor: colors.card,
        borderTopColor: colors.borderSubtle,
        borderTopWidth: StyleSheet.hairlineWidth,
        height: tabBarHeight,
        paddingBottom: bottomPad,
        paddingTop: 6,
      },
      tabBarShowLabel: false,
      tabBarActiveTintColor: colors.accent,
      tabBarInactiveTintColor: colors.muted,
      freezeOnBlur: true,
      lazy: true,
    }),
    [bottomPad, tabBarHeight],
  );

  return (
    <Tab.Navigator screenOptions={screenOptions}>
      <Tab.Screen
        name="Dashboard"
        component={DashStack}
        options={{
          headerShown: false,
          tabBarIcon: ({ focused }) => <TabIcon glyph="⚡" label="Scan" focused={focused} />,
        }}
      />
      <Tab.Screen
        name="Portfolio"
        component={PortfolioScreen}
        options={{
          title: 'Paper',
          tabBarIcon: ({ focused }) => <TabIcon glyph="◈" label="Paper" focused={focused} />,
        }}
      />
      <Tab.Screen
        name="Watchlist"
        component={WatchlistScreen}
        options={{
          tabBarIcon: ({ focused }) => <TabIcon glyph="★" label="Watch" focused={focused} />,
        }}
      />
      <Tab.Screen
        name="Learning"
        component={LearningScreen}
        options={{
          tabBarIcon: ({ focused }) => <TabIcon glyph="◎" label="Learn" focused={focused} />,
        }}
      />
      <Tab.Screen
        name="CoPilot"
        component={CoPilotScreen}
        options={{
          title: 'E-ve',
          tabBarIcon: ({ focused }) => <TabIcon glyph="✦" label="AI" focused={focused} />,
        }}
      />
      <Tab.Screen
        name="Settings"
        component={SettingsScreen}
        options={{
          tabBarIcon: ({ focused }) => <TabIcon glyph="⚙" label="Set" focused={focused} />,
        }}
      />
    </Tab.Navigator>
  );
}

const styles = StyleSheet.create({
  tabIcon: { alignItems: 'center', justifyContent: 'center', minWidth: 48 },
  tabLabel: { ...type.caption, fontSize: 10, marginTop: 2 },
});
