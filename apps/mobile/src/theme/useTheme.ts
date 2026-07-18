import { useAppSelector } from "@/store/hooks";
import { getColors } from "./colors";

export function useTheme() {
  const theme = useAppSelector((state) => state.ui.theme);
  return { theme, colors: getColors(theme) };
}
