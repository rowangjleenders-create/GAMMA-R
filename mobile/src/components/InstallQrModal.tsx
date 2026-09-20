import React from 'react';
import {
  Modal, View, Text, StyleSheet, TouchableOpacity, TextInput, ScrollView,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import QRCode from 'react-native-qrcode-svg';
import { colors, space, radius } from '../theme/tokens';

type Props = {
  visible: boolean;
  url: string;
  onChangeUrl: (v: string) => void;
  onClose: () => void;
  onSaveUrl: () => void;
};

export function InstallQrModal({ visible, url, onChangeUrl, onClose, onSaveUrl }: Props) {
  const insets = useSafeAreaInsets();
  const qrValue = (url || '').trim() || 'https://example.com/install.html';

  return (
    <Modal visible={visible} animationType="slide" transparent onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, space.md) }]}>
          <ScrollView contentContainerStyle={styles.sheetInner} keyboardShouldPersistTaps="handled">
            <Text style={styles.title}>Install on your iPhone</Text>
            <Text style={styles.hint}>
              Scan this QR to open your install landing page (Expo Go link + notes for TestFlight / IPA).
              Private single-user install — not public App Store distribution.
            </Text>

            <View style={styles.qrWrap}>
              <QRCode
                value={qrValue}
                size={200}
                backgroundColor={colors.card}
                color={colors.text}
              />
            </View>

            <Text style={styles.label}>Install page URL</Text>
            <TextInput
              style={styles.input}
              value={url}
              onChangeText={onChangeUrl}
              autoCapitalize="none"
              autoCorrect={false}
              placeholder="http://192.168.1.10:3333/install.html"
              placeholderTextColor={colors.muted}
            />
            <Text style={styles.hint}>
              Host <Text style={styles.code}>mobile/web/install.html</Text> (or{' '}
              <Text style={styles.code}>npm run install-page</Text>). Save the LAN URL so the QR stays correct.
            </Text>

            <TouchableOpacity style={styles.btn} onPress={onSaveUrl}>
              <Text style={styles.btnText}>Save URL</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.btn, styles.btnGhost]} onPress={onClose}>
              <Text style={styles.btnText}>Close</Text>
            </TouchableOpacity>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: colors.overlay,
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: colors.card,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    maxHeight: '88%',
  },
  sheetInner: { padding: space.xl, paddingBottom: space.lg },
  title: { color: colors.text, fontSize: 18, fontWeight: '800', marginBottom: space.sm },
  hint: { color: colors.muted, fontSize: 12, marginBottom: space.md, lineHeight: 17 },
  code: { color: colors.text, fontFamily: 'monospace' },
  qrWrap: {
    alignSelf: 'center',
    backgroundColor: colors.card,
    padding: space.lg,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: space.lg,
  },
  label: { color: colors.muted, marginBottom: 4 },
  input: {
    backgroundColor: colors.cardAlt,
    color: colors.text,
    padding: space.md,
    borderRadius: radius.sm + 2,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: space.sm,
  },
  btn: {
    backgroundColor: colors.accent,
    padding: 14,
    borderRadius: radius.sm + 2,
    alignItems: 'center',
    marginTop: space.sm,
  },
  btnGhost: { backgroundColor: colors.locked },
  btnText: { color: colors.white, fontWeight: '700' },
});
