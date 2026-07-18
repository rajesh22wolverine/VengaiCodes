import { StyleSheet, Text, TextInput, TextInputProps, View } from "react-native";
import { useTheme } from "@/theme/useTheme";

interface TextFieldProps extends TextInputProps {
  label: string;
  error?: string;
  rightElement?: React.ReactNode;
}

export default function TextField({ label, error, rightElement, style, ...inputProps }: TextFieldProps) {
  const { colors } = useTheme();

  return (
    <View style={styles.wrapper}>
      <Text style={[styles.label, { color: colors.textPrimary }]}>{label}</Text>
      <View style={styles.inputRow}>
        <TextInput
          placeholderTextColor={colors.textTertiary}
          style={[
            styles.input,
            {
              color: colors.textPrimary,
              backgroundColor: colors.surface,
              borderColor: error ? colors.error : colors.border,
            },
            rightElement ? { paddingRight: 44 } : null,
            style,
          ]}
          {...inputProps}
        />
        {rightElement && <View style={styles.rightElement}>{rightElement}</View>}
      </View>
      {error && <Text style={[styles.error, { color: colors.error }]}>{error}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: { marginBottom: 16 },
  label: { fontSize: 13, fontWeight: "600", marginBottom: 6 },
  inputRow: { position: "relative", justifyContent: "center" },
  input: {
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
  },
  rightElement: { position: "absolute", right: 12 },
  error: { marginTop: 6, fontSize: 12 },
});
