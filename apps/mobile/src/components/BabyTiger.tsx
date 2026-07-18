import { Text, TextStyle } from "react-native";

export type TigerExpression =
  | "idle"
  | "happy"
  | "sad"
  | "thinking"
  | "excited"
  | "coding"
  | "celebrating"
  | "investigating"
  | "serious"
  | "concerned"
  | "waving";

// Static emoji mascot — the RN equivalent of desktop's animated BabyTiger component.
// Framer Motion / Lottie animation isn't ported (see mobile parity plan); a small expression
// badge keeps some of that personality without needing an animation dependency.
const EXPRESSION_BADGE: Partial<Record<TigerExpression, string>> = {
  happy: "😺",
  sad: "😿",
  thinking: "🤔",
  excited: "🤩",
  coding: "💻",
  celebrating: "🎉",
  investigating: "🔍",
  concerned: "😟",
  waving: "👋",
};

interface BabyTigerProps {
  size?: number;
  expression?: TigerExpression;
  style?: TextStyle;
}

export default function BabyTiger({ size = 32, expression = "idle", style }: BabyTigerProps) {
  const badge = EXPRESSION_BADGE[expression];
  return (
    <Text style={[{ fontSize: size * 0.7 }, style]}>
      🐯{badge ? <Text style={{ fontSize: size * 0.35 }}>{badge}</Text> : null}
    </Text>
  );
}
