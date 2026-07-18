import { createSlice, createAsyncThunk, PayloadAction } from "@reduxjs/toolkit";
import apiClient from "@/lib/api";

export interface AppNotification {
  id: string;
  title: string;
  message: string;
  type: "info" | "success" | "warning" | "error" | "tiger_stamp" | "marketplace" | "admin";
  is_read: boolean;
  created_at: string;
  link?: string | null;
}

interface NotificationState {
  items: AppNotification[];
  unreadCount: number;
  isLoading: boolean;
}

const initialState: NotificationState = {
  items: [],
  unreadCount: 0,
  isLoading: false,
};

/** GET /notifications */
export const fetchNotifications = createAsyncThunk("notifications/fetchAll", async (_, { rejectWithValue }) => {
  try {
    const { data } = await apiClient.get("/notifications");
    return data.notifications as AppNotification[];
  } catch (error: any) {
    return rejectWithValue(error.message || "Failed to load notifications");
  }
});

/** POST /notifications/:id/read */
export const markNotificationRead = createAsyncThunk("notifications/markRead", async (id: string, { rejectWithValue }) => {
  try {
    await apiClient.post(`/notifications/${id}/read`);
    return id;
  } catch (error: any) {
    return rejectWithValue(error.message || "Failed to update notification");
  }
});

const notificationSlice = createSlice({
  name: "notifications",
  initialState,
  reducers: {
    addNotification: (state, action: PayloadAction<AppNotification>) => {
      state.items.unshift(action.payload);
      if (!action.payload.is_read) state.unreadCount += 1;
    },
    clearAll: (state) => {
      state.items = [];
      state.unreadCount = 0;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchNotifications.pending, (state) => {
        state.isLoading = true;
      })
      .addCase(fetchNotifications.fulfilled, (state, action) => {
        state.isLoading = false;
        state.items = action.payload;
        state.unreadCount = action.payload.filter((n) => !n.is_read).length;
      })
      .addCase(fetchNotifications.rejected, (state) => {
        state.isLoading = false;
      });

    builder.addCase(markNotificationRead.fulfilled, (state, action) => {
      const notif = state.items.find((n) => n.id === action.payload);
      if (notif && !notif.is_read) {
        notif.is_read = true;
        state.unreadCount = Math.max(0, state.unreadCount - 1);
      }
    });
  },
});

export const { addNotification, clearAll } = notificationSlice.actions;
export default notificationSlice.reducer;
