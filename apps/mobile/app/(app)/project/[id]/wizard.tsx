import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import { ArrowLeft, Send } from "lucide-react-native";

import apiClient from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import BabyTiger from "@/components/BabyTiger";

interface Message {
  role: "user" | "ai";
  content: string;
}

const LAYER_LABELS = ["Core Idea", "Problem", "Key Features", "Platforms", "Target Users", "Monetization", "References", "App Name"];

export default function WizardScreen() {
  const { id: projectId } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { showToast } = useToast();
  const listRef = useRef<FlatList>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(true);
  const [currentLayer, setCurrentLayer] = useState(1);
  const [understandingScore, setUnderstandingScore] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [projectName, setProjectName] = useState("");

  useEffect(() => {
    const loadHistory = async () => {
      try {
        const { data } = await apiClient.get(`/wizard/${projectId}/history`);
        setProjectName(data.project_name);
        if (data.conversation && data.conversation.length > 0) {
          setMessages(data.conversation);
          setCurrentLayer(data.current_layer);
          setUnderstandingScore(data.understanding_score);
          if (data.understanding_score >= 100) setIsComplete(true);
        } else {
          setMessages([
            {
              role: "ai",
              content: `Hi! I'm Baby Tiger 🐯 and I'm SO excited to help you build your app!\n\nI can see your idea: "${data.raw_idea}"\n\nI just need to ask you 8 quick questions to fully understand what you want to build. Let's start!\n\nQuestion 1/8 — Core Idea:\nWho is this app mainly for, and what's the ONE main thing they'll do in it?`,
            },
          ]);
        }
      } catch {
        showToast("Failed to load project. Please try again.", "error");
        router.replace("/(app)/(tabs)/home");
      } finally {
        setIsHistoryLoading(false);
      }
    };
    if (projectId) loadHistory();
  }, [projectId]);

  useEffect(() => {
    if (messages.length > 0) {
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 100);
    }
  }, [messages.length, isLoading]);

  const sendMessage = async () => {
    if (!input.trim() || isLoading || isComplete) return;

    const userMessage = input.trim();
    setInput("");
    setIsLoading(true);
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);

    try {
      const { data } = await apiClient.post("/wizard/message", {
        project_id: projectId,
        user_message: userMessage,
        current_layer: currentLayer,
      });

      setMessages((prev) => [...prev, { role: "ai", content: data.ai_response }]);
      setCurrentLayer(data.next_layer);
      setUnderstandingScore(data.understanding_score);

      if (data.is_complete) {
        setIsComplete(true);
        showToast("Baby Tiger understands your app! 🐯");
      }
    } catch (error: any) {
      showToast(error.message || "Baby Tiger had a problem. Try again!", "error");
    } finally {
      setIsLoading(false);
    }
  };

  if (isHistoryLoading) {
    return (
      <View style={[styles.centered, { backgroundColor: colors.background }]}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  const activeLayer = Math.min(currentLayer, LAYER_LABELS.length);

  return (
    <KeyboardAvoidingView
      style={[styles.screen, { backgroundColor: colors.background }]}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View style={[styles.header, { borderBottomColor: colors.border, backgroundColor: colors.surface }]}>
        <Pressable onPress={() => router.push("/(app)/(tabs)/home")} hitSlop={8}>
          <ArrowLeft size={18} color={colors.textSecondary} />
        </Pressable>
        <BabyTiger size={28} expression="happy" />
        <View style={{ flex: 1 }}>
          <Text style={[styles.headerTitle, { color: colors.textPrimary }]} numberOfLines={1}>
            {projectName || "Your Project"}
          </Text>
          <Text style={[styles.headerSubtitle, { color: colors.textTertiary }]}>Baby Tiger is understanding your idea</Text>
        </View>
        <View style={{ alignItems: "flex-end" }}>
          <Text style={{ color: colors.textTertiary, fontSize: 10 }}>Understanding</Text>
          <Text style={{ color: colors.primary, fontSize: 14, fontWeight: "700" }}>{Math.round(understandingScore)}%</Text>
        </View>
      </View>

      <View style={[styles.layerBar, { borderBottomColor: colors.border, backgroundColor: colors.surface }]}>
        {LAYER_LABELS.map((label, i) => {
          const step = i + 1;
          const state = step < currentLayer ? "done" : step === currentLayer ? "active" : "pending";
          return (
            <View
              key={label}
              style={[
                styles.layerDot,
                {
                  backgroundColor: state === "done" ? colors.success : state === "active" ? colors.primary : colors.border,
                },
              ]}
            >
              <Text style={{ color: state === "pending" ? colors.textTertiary : "#fff", fontSize: 10, fontWeight: "700" }}>
                {state === "done" ? "✓" : step}
              </Text>
            </View>
          );
        })}
      </View>

      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(_, i) => String(i)}
        contentContainerStyle={styles.messagesContent}
        renderItem={({ item }) => (
          <View style={[styles.messageRow, item.role === "user" && styles.messageRowReversed]}>
            {item.role === "ai" && <BabyTiger size={26} expression="happy" />}
            <View
              style={[
                styles.bubble,
                item.role === "user"
                  ? { backgroundColor: colors.primary, borderTopRightRadius: 4 }
                  : { backgroundColor: colors.surface, borderColor: colors.border, borderWidth: 1, borderTopLeftRadius: 4 },
              ]}
            >
              <Text style={{ color: item.role === "user" ? "#fff" : colors.textPrimary, fontSize: 13, lineHeight: 19 }}>
                {item.content.replace(/\*\*(.*?)\*\*/g, "$1")}
              </Text>
            </View>
          </View>
        )}
        ListFooterComponent={
          isComplete ? (
            <View style={styles.completeCard}>
              <BabyTiger size={64} expression="celebrating" style={styles.completeEmoji} />
              <Text style={[styles.completeTitle, { color: colors.textPrimary }]}>Baby Tiger understands your app! 🐯</Text>
              <Text style={[styles.completeSubtitle, { color: colors.textSecondary }]}>
                Understanding score: {Math.round(understandingScore)}% — Ready to generate requirements!
              </Text>
              <Pressable
                style={[styles.completeButton, { backgroundColor: colors.primary }]}
                onPress={() => router.replace(`/(app)/project/${projectId}/requirements` as any)}
              >
                <Text style={styles.completeButtonText}>Generate Requirements Document →</Text>
              </Pressable>
            </View>
          ) : isLoading ? (
            <View style={styles.messageRow}>
              <BabyTiger size={26} expression="thinking" />
              <ActivityIndicator color={colors.primary} />
            </View>
          ) : null
        }
      />

      {!isComplete && (
        <View style={[styles.inputBar, { borderTopColor: colors.border, backgroundColor: colors.surface }]}>
          <View style={styles.inputRow}>
            <TextInput
              value={input}
              onChangeText={setInput}
              placeholder="Type your answer..."
              placeholderTextColor={colors.textTertiary}
              multiline
              editable={!isLoading}
              style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
            />
            <Pressable
              onPress={sendMessage}
              disabled={!input.trim() || isLoading}
              style={[styles.sendButton, { backgroundColor: colors.primary }, (!input.trim() || isLoading) && { opacity: 0.5 }]}
            >
              {isLoading ? <ActivityIndicator size="small" color="#fff" /> : <Send size={18} color="#fff" />}
            </Pressable>
          </View>
          <Text style={[styles.questionLabel, { color: colors.textTertiary }]}>
            Question {activeLayer} of {LAYER_LABELS.length} — {LAYER_LABELS[activeLayer - 1]}
          </Text>
        </View>
      )}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  centered: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  emoji: { fontSize: 20 },
  headerTitle: { fontSize: 13, fontWeight: "700" },
  headerSubtitle: { fontSize: 10 },
  layerBar: { flexDirection: "row", gap: 4, paddingHorizontal: 16, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth },
  layerDot: { flex: 1, height: 20, borderRadius: 10, alignItems: "center", justifyContent: "center" },
  messagesContent: { padding: 16, gap: 12 },
  messageRow: { flexDirection: "row", gap: 8, marginBottom: 12, alignItems: "flex-end" },
  messageRowReversed: { flexDirection: "row-reverse" },
  bubbleTiger: { fontSize: 20 },
  bubble: { maxWidth: "78%", borderRadius: 16, paddingHorizontal: 14, paddingVertical: 10 },
  completeCard: { alignItems: "center", paddingVertical: 24, gap: 8 },
  completeEmoji: { fontSize: 48 },
  completeTitle: { fontSize: 16, fontWeight: "700", textAlign: "center" },
  completeSubtitle: { fontSize: 13, textAlign: "center", marginBottom: 8 },
  completeButton: { paddingHorizontal: 20, paddingVertical: 12, borderRadius: 12 },
  completeButtonText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  inputBar: { borderTopWidth: StyleSheet.hairlineWidth, padding: 12 },
  inputRow: { flexDirection: "row", gap: 8, alignItems: "flex-end" },
  input: { flex: 1, borderWidth: 1, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 10, fontSize: 13, maxHeight: 100 },
  sendButton: { width: 42, height: 42, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  questionLabel: { fontSize: 10, textAlign: "center", marginTop: 8 },
});
