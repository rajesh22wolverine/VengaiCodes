import { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { Provider } from "react-redux";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { Slot } from "expo-router";
import { store } from "@/store";
import { useAppDispatch } from "@/store/hooks";
import { checkSession } from "@/store/slices/authSlice";
import { hydrateUI } from "@/store/slices/uiSlice";
import { ToastProvider } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";

export const unstable_settings = {
  initialRouteName: "(auth)",
};

function Bootstrap({ children }: { children: React.ReactNode }) {
  const dispatch = useAppDispatch();
  const [ready, setReady] = useState(false);
  const { colors } = useTheme();

  useEffect(() => {
    Promise.all([dispatch(checkSession()), dispatch(hydrateUI())]).finally(() => setReady(true));
  }, [dispatch]);

  if (!ready) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.background }}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return <>{children}</>;
}

export default function RootLayout() {
  return (
    <Provider store={store}>
      <SafeAreaProvider>
        <ToastProvider>
          <Bootstrap>
            <Slot />
          </Bootstrap>
        </ToastProvider>
      </SafeAreaProvider>
    </Provider>
  );
}
