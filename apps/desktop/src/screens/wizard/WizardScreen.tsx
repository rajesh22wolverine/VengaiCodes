import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Send, ArrowLeft, Loader2 } from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

interface Message {
  role: "user" | "ai";
  content: string;
  layer?: number;
}

const LAYER_LABELS = [
  "Core Idea",
  "Problem",
  "Key Features",
  "Platforms",
  "Target Users",
  "Monetization",
  "References",
  "App Name",
];

export default function WizardScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();
  const bottomRef = useRef<HTMLDivElement>(null);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [currentLayer, setCurrentLayer] = useState(1);
  const [understandingScore, setUnderstandingScore] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [tigerExpression, setTigerExpression] = useState<"excited" | "thinking" | "happy">("excited");

  // Load conversation history on mount
  useEffect(() => {
    const loadHistory = async () => {
      try {
        const { data } = await apiClient.get(`/wizard/${projectId}/history`);
        setProjectName(data.project_name);
        if (data.conversation && data.conversation.length > 0) {
          setMessages(data.conversation);
          setCurrentLayer(data.current_layer);
          setUnderstandingScore(data.understanding_score);
          if (data.understanding_score >= 100) {
            setIsComplete(true);
          }
        } else {
          // Start the conversation with Baby Tiger's opening
          const opening: Message = {
            role: "ai",
            content: `Hi! I'm Baby Tiger 🐯 and I'm SO excited to help you build your app!\n\nI can see your idea: "${data.raw_idea}"\n\nI just need to ask you 8 quick questions to fully understand what you want to build. Let's start!\n\n**Question 1/8 — Core Idea:**\nWho is this app mainly for, and what's the ONE main thing they'll do in it?`,
          };
          setMessages([opening]);
        }
      } catch (error) {
        toast.error("Failed to load project. Please try again.");
        navigate("/home");
      }
    };
    if (projectId) loadHistory();
  }, [projectId]);

  // Auto-scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendMessage = async () => {
    if (!input.trim() || isLoading || isComplete) return;

    const userMessage = input.trim();
    setInput("");
    setIsLoading(true);
    setTigerExpression("thinking");

    // Add user message immediately
    setMessages(prev => [...prev, { role: "user", content: userMessage }]);

    try {
      const { data } = await apiClient.post("/wizard/message", {
        project_id: projectId,
        user_message: userMessage,
        current_layer: currentLayer,
      });

      setMessages(prev => [...prev, { role: "ai", content: data.ai_response }]);
      setCurrentLayer(data.next_layer);
      setUnderstandingScore(data.understanding_score);
      setTigerExpression("happy");

      if (data.is_complete) {
        setIsComplete(true);
        toast.success("Baby Tiger understands your app! 🐯");
      }
    } catch (error: any) {
      toast.error(error.message || "Baby Tiger had a problem. Try again!");
      setTigerExpression("excited");
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--color-background)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <button
          onClick={() => navigate("/home")}
          className="p-2 rounded-lg hover:bg-[var(--color-surface-raised)] transition-colors"
        >
          <ArrowLeft className="w-4 h-4 text-[var(--color-text-secondary)]" />
        </button>
        <BabyTiger size={36} expression={tigerExpression} />
        <div className="flex-1">
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">
            {projectName || "Your Project"}
          </h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Baby Tiger is understanding your idea
          </p>
        </div>
        {/* Understanding Score */}
        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className="text-xs text-[var(--color-text-tertiary)]">Understanding</p>
            <p className="text-sm font-bold text-[var(--color-primary)]">
              {Math.round(understandingScore)}%
            </p>
          </div>
          <div className="w-24 h-2 rounded-full bg-[var(--color-surface-raised)] overflow-hidden">
            <motion.div
              className="h-full rounded-full bg-[var(--color-primary)]"
              animate={{ width: `${understandingScore}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </div>
      </div>

      {/* Layer progress */}
      <div className="flex items-center gap-1.5 px-6 py-2 bg-[var(--color-surface)] border-b border-[var(--color-border)] flex-shrink-0">
        {LAYER_LABELS.map((label, i) => (
          <div key={label} className="flex items-center gap-1.5 flex-1">
            <div className={`flex items-center gap-1 ${i + 1 < currentLayer ? "opacity-100" : i + 1 === currentLayer ? "opacity-100" : "opacity-30"}`}>
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
                i + 1 < currentLayer
                  ? "bg-[var(--color-success)] text-white"
                  : i + 1 === currentLayer
                  ? "bg-[var(--color-primary)] text-white"
                  : "bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)]"
              }`}>
                {i + 1 < currentLayer ? "✓" : i + 1}
              </div>
              <span className="text-xs text-[var(--color-text-tertiary)] hidden sm:block truncate">
                {label}
              </span>
            </div>
            {i < LAYER_LABELS.length - 1 && <div className="flex-1 h-px bg-[var(--color-border)] hidden sm:block" />}
          </div>
        ))}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <AnimatePresence>
          {messages.map((msg, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex gap-3 ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}
            >
              {msg.role === "ai" && (
                <div className="flex-shrink-0">
                  <BabyTiger size={32} expression="happy" />
                </div>
              )}
              <div className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "bg-[var(--color-primary)] text-white rounded-tr-sm"
                  : "bg-[var(--color-surface)] text-[var(--color-text-primary)] border border-[var(--color-border)] rounded-tl-sm"
              }`}>
                {msg.content.split("\n").map((line, j) => (
                  <p key={j} className={j > 0 ? "mt-1" : ""}>
                    {line.replace(/\*\*(.*?)\*\*/g, "$1")}
                  </p>
                ))}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {isLoading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex gap-3"
          >
            <BabyTiger size={32} expression="thinking" />
            <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl rounded-tl-sm px-4 py-3">
              <div className="flex gap-1">
                {[0, 1, 2].map(i => (
                  <motion.div
                    key={i}
                    className="w-2 h-2 rounded-full bg-[var(--color-primary)]"
                    animate={{ y: [0, -6, 0] }}
                    transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.15 }}
                  />
                ))}
              </div>
            </div>
          </motion.div>
        )}

        {isComplete && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex flex-col items-center gap-4 py-6"
          >
            <BabyTiger size={80} expression="excited" />
            <div className="text-center">
              <h3 className="text-lg font-bold text-[var(--color-text-primary)] mb-1">
                Baby Tiger understands your app! 🐯
              </h3>
              <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                Understanding score: {Math.round(understandingScore)}% — Ready to generate requirements!
              </p>
              <button
                onClick={() => navigate(`/project/${projectId}/requirements`)}
                className="px-6 py-3 rounded-xl bg-[var(--color-primary)] text-white font-semibold hover:bg-[var(--color-primary-hover)] transition-colors"
              >
                Generate Requirements Document →
              </button>
            </div>
          </motion.div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      {!isComplete && (
        <div className="flex-shrink-0 px-6 py-4 border-t border-[var(--color-border)] bg-[var(--color-surface)]">
          <div className="flex gap-3 items-end">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type your answer... (Enter to send)"
              rows={2}
              disabled={isLoading}
              className="flex-1 px-4 py-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:ring-2 focus:ring-[var(--color-primary)] focus:border-[var(--color-primary)] outline-none resize-none text-sm disabled:opacity-50"
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || isLoading}
              className="p-3 rounded-xl bg-[var(--color-primary)] text-white hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
            >
              {isLoading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
          <p className="text-xs text-[var(--color-text-tertiary)] mt-2 text-center">
            Question {Math.min(currentLayer, LAYER_LABELS.length)} of {LAYER_LABELS.length} — {LAYER_LABELS[Math.min(currentLayer, LAYER_LABELS.length) - 1]}
          </p>
        </div>
      )}
    </div>
  );
}
