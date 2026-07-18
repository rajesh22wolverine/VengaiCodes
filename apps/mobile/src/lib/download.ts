import { File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import { getAccessToken } from "@/lib/storage";

const API_BASE_URL = process.env.EXPO_PUBLIC_API_URL || "https://vengaicode-backend.onrender.com";

/**
 * Downloads a binary response from the backend (ZIP exports, build artifacts) straight to disk
 * with the auth header attached, then opens the native share sheet — the RN equivalent of the
 * web app's blob-URL download-link trick.
 */
export async function downloadAndShareFile(
  apiPath: string,
  filename: string,
  params?: Record<string, string | boolean | undefined>
): Promise<string> {
  const token = await getAccessToken();
  const query = params
    ? "?" +
      Object.entries(params)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
        .join("&")
    : "";
  const url = `${API_BASE_URL}/api/v1${apiPath}${query && query !== "?" ? query : ""}`;

  const destination = new File(Paths.cache, filename);
  const file = await File.downloadFileAsync(url, destination, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    idempotent: true,
  });

  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(file.uri);
  }

  return file.uri;
}
