import { useEffect } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useSelector, useDispatch } from "react-redux";
import { RootState } from "@/store";
import { setTheme } from "@/store/slices/uiSlice";

// Screens
import LoginScreen from "@/screens/auth/LoginScreen";
import SignupScreen from "@/screens/auth/SignupScreen";
import OTPScreen from "@/screens/auth/OTPScreen";
import ForgotPasswordScreen from "@/screens/auth/ForgotPasswordScreen";
import HomeScreen from "@/screens/home/HomeScreen";
import WizardScreen from "@/screens/wizard/WizardScreen";
import UIUXScreen from "@/screens/uiux/UIUXScreen";
import ArchitectureScreen from "@/screens/architecture/ArchitectureScreen";
import CodeGenScreen from "@/screens/codegen/CodeGenScreen";
import TestingScreen from "@/screens/testing/TestingScreen";
import ExportScreen from "@/screens/export/ExportScreen";
import SettingsScreen from "@/screens/settings/SettingsScreen";
import OnboardingScreen from "@/screens/onboarding/OnboardingScreen";
import MainLayout from "@/components/layout/MainLayout";

// Protected route wrapper
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useSelector((state: RootState) => state.auth);
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

// Auth route wrapper — redirect if already logged in
function AuthRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useSelector((state: RootState) => state.auth);
  if (isAuthenticated) return <Navigate to="/home" replace />;
  return <>{children}</>;
}

export default function App() {
  const dispatch = useDispatch();
  const { theme, isFirstLaunch } = useSelector((state: RootState) => state.ui);

  // Apply theme on load and change
  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [theme]);

  // Load saved theme from localStorage on first render
  useEffect(() => {
    const savedTheme = localStorage.getItem("vengaicode-theme") as "light" | "dark" | null;
    if (savedTheme) {
      dispatch(setTheme(savedTheme));
    } else {
      // Detect system preference
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      dispatch(setTheme(prefersDark ? "dark" : "light"));
    }
  }, []);

  return (
    <Routes>
      {/* Public auth routes */}
      <Route path="/login" element={<AuthRoute><LoginScreen /></AuthRoute>} />
      <Route path="/signup" element={<AuthRoute><SignupScreen /></AuthRoute>} />
      <Route path="/otp" element={<AuthRoute><OTPScreen /></AuthRoute>} />
      <Route path="/forgot-password" element={<AuthRoute><ForgotPasswordScreen /></AuthRoute>} />

      {/* First launch onboarding */}
      <Route path="/onboarding" element={
        <ProtectedRoute>
          {isFirstLaunch ? <OnboardingScreen /> : <Navigate to="/home" replace />}
        </ProtectedRoute>
      } />

      {/* Protected app routes with main layout */}
      <Route path="/" element={<ProtectedRoute><MainLayout /></ProtectedRoute>}>
        <Route index element={<Navigate to="/home" replace />} />
        <Route path="home" element={<HomeScreen />} />
        <Route path="project/:id/wizard" element={<WizardScreen />} />
        <Route path="project/:id/uiux" element={<UIUXScreen />} />
        <Route path="project/:id/architecture" element={<ArchitectureScreen />} />
        <Route path="project/:id/codegen" element={<CodeGenScreen />} />
        <Route path="project/:id/testing" element={<TestingScreen />} />
        <Route path="project/:id/export" element={<ExportScreen />} />
        <Route path="settings" element={<SettingsScreen />} />
      </Route>

      {/* Catch all */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
