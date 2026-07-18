import { createSlice, PayloadAction } from "@reduxjs/toolkit";

export interface WizardMessage {
  role: "ai" | "user";
  content: string;
  timestamp: string;
}

interface WizardState {
  conversation: WizardMessage[];
  currentLayer: number; // 1-7
  understandingScore: number; // 0-100
  isAiThinking: boolean;
}

const initialState: WizardState = {
  conversation: [],
  currentLayer: 1,
  understandingScore: 0,
  isAiThinking: false,
};

const wizardSlice = createSlice({
  name: "wizard",
  initialState,
  reducers: {
    addMessage: (state, action: PayloadAction<WizardMessage>) => {
      state.conversation.push(action.payload);
    },
    setCurrentLayer: (state, action: PayloadAction<number>) => {
      state.currentLayer = action.payload;
    },
    setUnderstandingScore: (state, action: PayloadAction<number>) => {
      state.understandingScore = Math.max(0, Math.min(100, action.payload));
    },
    setAiThinking: (state, action: PayloadAction<boolean>) => {
      state.isAiThinking = action.payload;
    },
    resetWizard: (state) => {
      state.conversation = [];
      state.currentLayer = 1;
      state.understandingScore = 0;
      state.isAiThinking = false;
    },
  },
});

export const { addMessage, setCurrentLayer, setUnderstandingScore, setAiThinking, resetWizard } = wizardSlice.actions;
export default wizardSlice.reducer;
