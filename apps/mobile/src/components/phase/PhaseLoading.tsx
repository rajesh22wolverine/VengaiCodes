import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { useTheme } from "@/theme/useTheme";
import BabyTiger from "@/components/BabyTiger";
import { GenerationJob, jobProgressPercent } from "@/lib/generationJob";

interface Props {
  message: string;
  /**
   * Set while a background generation job is running. UI/UX and code
   * generation make one AI call per screen (and per table, for code), so
   * on a real project they take minutes — long enough that a bare
   * spinner tells the user nothing about whether anything is happening.
   */
  job?: GenerationJob | null;
  onCancel?: () => void;
  isCancelling?: boolean;
}

export default function PhaseLoading({ message, job, onCancel, isCancelling }: Props) {
  const { colors } = useTheme();
  const percent = jobProgressPercent(job ?? null);
  const isRunning = job?.status === "running" || job?.status === "queued";
  const stopping = isCancelling || job?.cancel_requested;

  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      <BabyTiger size={64} expression="thinking" />
      <ActivityIndicator color={colors.primary} />
      <Text style={[styles.message, { color: colors.textSecondary }]}>{message}</Text>

      {job && job.total_steps > 0 && (
        <View style={styles.progress}>
          <View style={[styles.track, { backgroundColor: colors.surface }]}>
            <View
              style={[
                styles.fill,
                { backgroundColor: colors.primary, width: `${percent ?? 0}%` },
              ]}
            />
          </View>
          <View style={styles.progressRow}>
            <Text style={[styles.step, { color: colors.textTertiary }]} numberOfLines={1}>
              {job.current_step || "Getting started…"}
            </Text>
            <Text style={[styles.count, { color: colors.textTertiary }]}>
              {job.completed_steps}/{job.total_steps}
            </Text>
          </View>
        </View>
      )}

      {job && (
        <Text style={[styles.note, { color: colors.textTertiary }]}>
          This keeps going if you leave — come back to this screen to pick it up.
        </Text>
      )}

      {onCancel && isRunning && (
        <Pressable
          onPress={onCancel}
          disabled={stopping}
          style={[
            styles.cancel,
            { borderColor: colors.border, opacity: stopping ? 0.6 : 1 },
          ]}
        >
          <Text style={[styles.cancelText, { color: colors.textSecondary }]}>
            {job?.cancel_requested ? "Stopping after this step…" : "Stop"}
          </Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12, padding: 24 },
  message: { fontSize: 13, textAlign: "center" },
  progress: { width: "100%", maxWidth: 320, gap: 6 },
  track: { height: 6, borderRadius: 3, overflow: "hidden" },
  fill: { height: "100%", borderRadius: 3 },
  progressRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 },
  step: { fontSize: 11, flexShrink: 1 },
  count: { fontSize: 11, fontVariant: ["tabular-nums"] },
  note: { fontSize: 11, textAlign: "center", maxWidth: 320 },
  cancel: { paddingHorizontal: 16, paddingVertical: 8, borderRadius: 12, borderWidth: 1 },
  cancelText: { fontSize: 12, fontWeight: "500" },
});
