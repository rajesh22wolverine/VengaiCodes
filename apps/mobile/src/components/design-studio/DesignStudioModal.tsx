import { useRef, useState } from "react";
import { ActivityIndicator, Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { WebView, type WebViewMessageEvent } from "react-native-webview";
import { Save, X } from "lucide-react-native";

import { useTheme } from "@/theme/useTheme";
import { buildDesignStudioDocument } from "@/lib/designStudioDocument";

interface DesignStudioModalProps {
  visible: boolean;
  html: string;
  css: string;
  onSave: (html: string, css: string) => void;
  onClose: () => void;
}

// Mobile counterpart to apps/desktop/src/components/design-studio/DesignStudio.tsx
// — a real drag-and-drop GrapesJS canvas, hosted in a WebView since GrapesJS
// has no React Native binding. Save & Close asks the in-page editor for its
// current HTML/CSS via the same postMessage bridge the click-to-edit preview
// already uses elsewhere in this screen (see designPreview.ts).
export default function DesignStudioModal({ visible, html, css, onSave, onClose }: DesignStudioModalProps) {
  const { colors } = useTheme();
  const webViewRef = useRef<WebView>(null);
  const [isReady, setIsReady] = useState(false);

  const handleMessage = (event: WebViewMessageEvent) => {
    let data: any;
    try {
      data = JSON.parse(event.nativeEvent.data);
    } catch {
      return;
    }
    if (data?.source !== "vengaicode-design-studio") return;
    if (data.type === "ready") {
      setIsReady(true);
    } else if (data.type === "saved") {
      onSave(data.html, data.css || "");
    }
  };

  const handleSavePress = () => {
    // The inlined GrapesJS bundle can take a moment to finish executing on
    // slower devices — before that, window.__vengaiSave doesn't exist yet
    // and this would be a silent no-op.
    if (!isReady) return;
    webViewRef.current?.injectJavaScript("window.__vengaiSave && window.__vengaiSave(); true;");
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={[styles.screen, { backgroundColor: colors.background }]}>
        <View style={[styles.header, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <Text style={[styles.title, { color: colors.textPrimary }]}>Design Studio</Text>
          <View style={styles.headerActions}>
            <Pressable
              onPress={handleSavePress}
              disabled={!isReady}
              style={[styles.saveButton, { backgroundColor: colors.primary, opacity: isReady ? 1 : 0.5 }]}
            >
              {isReady ? <Save size={14} color="#fff" /> : <ActivityIndicator size="small" color="#fff" />}
              <Text style={styles.saveButtonText}>Save & Close</Text>
            </Pressable>
            <Pressable onPress={onClose} hitSlop={8} style={{ padding: 4 }}>
              <X size={20} color={colors.textSecondary} />
            </Pressable>
          </View>
        </View>

        {visible && (
          <WebView
            ref={webViewRef}
            source={{ html: buildDesignStudioDocument(html, css) }}
            onMessage={handleMessage}
            style={{ flex: 1 }}
            originWhitelist={["*"]}
          />
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  title: { fontSize: 15, fontWeight: "700" },
  headerActions: { flexDirection: "row", alignItems: "center", gap: 12 },
  saveButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  saveButtonText: { color: "#fff", fontWeight: "700", fontSize: 12 },
});
