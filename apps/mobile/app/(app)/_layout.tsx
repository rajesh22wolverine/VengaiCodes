import { Redirect, Stack } from "expo-router";
import { useAppSelector } from "@/store/hooks";

export default function AppLayout() {
  const isAuthenticated = useAppSelector((state) => state.auth.isAuthenticated);

  if (!isAuthenticated) {
    return <Redirect href="/(auth)/login" />;
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="(tabs)" />
      <Stack.Screen name="project/[id]/wizard" options={{ headerShown: true, title: "Requirements Wizard" }} />
      <Stack.Screen name="project/[id]/requirements" options={{ headerShown: true, title: "Requirements" }} />
      <Stack.Screen name="project/[id]/uiux" options={{ headerShown: true, title: "UI/UX Design" }} />
      <Stack.Screen name="project/[id]/architecture" options={{ headerShown: true, title: "Architecture" }} />
      <Stack.Screen name="project/[id]/codegen" options={{ headerShown: true, title: "Code Generation" }} />
      <Stack.Screen name="project/[id]/testing" options={{ headerShown: true, title: "Testing" }} />
      <Stack.Screen name="project/[id]/export" options={{ headerShown: true, title: "Export" }} />
      <Stack.Screen name="admin/index" options={{ headerShown: true, title: "Admin" }} />
      <Stack.Screen name="admin/users/[id]" options={{ headerShown: true, title: "User Detail" }} />
      <Stack.Screen name="admin/ai-models" options={{ headerShown: true, title: "AI Models" }} />
    </Stack>
  );
}
