import { createSlice, createAsyncThunk, PayloadAction } from "@reduxjs/toolkit";
import apiClient from "@/lib/api";

// ─── Types — mirror apps/backend/app/models/project.py ───
export type ProjectStatus = "draft" | "in_progress" | "completed" | "archived" | "deleted";
export type SDLCPhase =
  | "requirements"
  | "uiux"
  | "architecture"
  | "api_builder"
  | "code_generation"
  | "testing"
  | "export"
  | "completed";

export interface Project {
  id: string;
  name: string;
  description?: string | null;
  category: string;
  complexity?: "simple" | "standard" | "complex" | null;
  platforms: string[];
  status: ProjectStatus;
  current_phase: SDLCPhase;
  progress_percent: number;
  phases_completed: string[];
  understanding_score: number;
  estimated_build_time_minutes?: number | null;
  thumbnail_url?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

interface ProjectState {
  projects: Project[];
  activeProject: Project | null;
  isLoading: boolean;
  error: string | null;
}

const initialState: ProjectState = {
  projects: [],
  activeProject: null,
  isLoading: false,
  error: null,
};

/** GET /projects — list all projects for current user */
export const fetchProjects = createAsyncThunk("project/fetchAll", async (_, { rejectWithValue }) => {
  try {
    const { data } = await apiClient.get("/projects");
    return data.projects as Project[];
  } catch (error: any) {
    return rejectWithValue(error.message || "Failed to load projects");
  }
});

/** POST /projects — create a new project from raw idea text */
export const createProject = createAsyncThunk(
  "project/create",
  async ({ name, rawIdea }: { name: string; rawIdea: string }, { rejectWithValue }) => {
    try {
      const { data } = await apiClient.post("/projects", { name, raw_idea: rawIdea });
      return data.project as Project;
    } catch (error: any) {
      return rejectWithValue(error.message || "Failed to create project");
    }
  }
);

/** GET /projects/:id — fetch a single project (used by SDLC pipeline screens) */
export const fetchProject = createAsyncThunk("project/fetchOne", async (projectId: string, { rejectWithValue }) => {
  try {
    const { data } = await apiClient.get(`/projects/${projectId}`);
    return data.project as Project;
  } catch (error: any) {
    return rejectWithValue(error.message || "Failed to load project");
  }
});

/** DELETE /projects/:id — soft delete a project */
export const deleteProject = createAsyncThunk("project/delete", async (projectId: string, { rejectWithValue }) => {
  try {
    await apiClient.delete(`/projects/${projectId}`);
    return projectId;
  } catch (error: any) {
    return rejectWithValue(error.message || "Failed to delete project");
  }
});

/** POST /projects/:id/complete — mark project completed */
export const completeProject = createAsyncThunk("project/complete", async (projectId: string, { rejectWithValue }) => {
  try {
    const { data } = await apiClient.post(`/projects/${projectId}/complete`);
    return data.project as Project;
  } catch (error: any) {
    return rejectWithValue(error.message || "Failed to complete project");
  }
});

const projectSlice = createSlice({
  name: "project",
  initialState,
  reducers: {
    setActiveProject: (state, action: PayloadAction<Project | null>) => {
      state.activeProject = action.payload;
    },
    clearProjectError: (state) => {
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchProjects.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(fetchProjects.fulfilled, (state, action) => {
        state.isLoading = false;
        state.projects = action.payload;
      })
      .addCase(fetchProjects.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });

    builder
      .addCase(createProject.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(createProject.fulfilled, (state, action) => {
        state.isLoading = false;
        state.projects.unshift(action.payload);
        state.activeProject = action.payload;
      })
      .addCase(createProject.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });

    builder
      .addCase(fetchProject.pending, (state) => {
        state.isLoading = true;
        state.error = null;
      })
      .addCase(fetchProject.fulfilled, (state, action) => {
        state.isLoading = false;
        state.activeProject = action.payload;
      })
      .addCase(fetchProject.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
      });

    builder.addCase(completeProject.fulfilled, (state, action) => {
      state.activeProject = action.payload;
      state.projects = state.projects.map((p) => (p.id === action.payload.id ? action.payload : p));
    });

    builder.addCase(deleteProject.fulfilled, (state, action) => {
      state.projects = state.projects.filter((p) => p.id !== action.payload);
      if (state.activeProject?.id === action.payload) {
        state.activeProject = null;
      }
    });
  },
});

export const { setActiveProject, clearProjectError } = projectSlice.actions;
export default projectSlice.reducer;
