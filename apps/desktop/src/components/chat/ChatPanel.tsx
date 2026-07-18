import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { MessageCircle, X, Send, Loader2, Sparkles } from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

interface ChatMessage {
  id: string;
  phase: string;
  role: "user" | "assistant";
  content: string;
  intent: "question" | "requirement_change" | null;
  created_at: string;
}

interface ChatPanelProps {
  projectId: string | undefined;
  phase: string;
}

export default function ChatPanel({ projectId, phase }: ChatPanelProps) {
  const navigate = useNavigate();
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen && projectId) loadHistory();
  }, [isOpen, projectId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const loadHistory = async () => {
    setIsLoadingHistory(true);
    try {
      const { data } = await apiClient.get(`/chat/${projectId}/messages`);
      setMessages(data.messages || []);
    } catch (error: any) {
      toast.error(error.message || "Failed to load chat history.");
    } finally {
      setIsLoadingHistory(false);
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isSending || !projectId) return;

    const optimisticUserMessage: ChatMessage = {
      id: `pending-${Date.now()}`,
      phase,
      role: "user",
      content: text,
      intent: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticUserMessage]);
    setInput("");
    setIsSending(true);

    try {
      const { data } = await apiClient.post(`/chat/${projectId}/message`, {
        message: text,
        phase,
      });
      setMessages((prev) => [...prev, data.message]);

      if (data.requirements_updated && data.redirect_to) {
        toast.success("Requirements updated! Taking you back to review them 🐯", {
          duration: 4000,
        });
        setIsOpen(false);
        navigate(data.redirect_to);
      }
    } catch (error: any) {
      toast.error(error.message || "Baby Tiger couldn't respond. Please try again.");
      setMessages((prev) => prev.filter((m) => m.id !== optimisticUserMessage.id));
      setInput(text);
    } finally {
      setIsSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      {/* Floating toggle button */}
      <motion.button
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        onClick={() => setIsOpen((prev) => !prev)}
        className="fixed bottom-6 right-6 z-40 w-14 h-14 rounded-full bg-[var(--color-primary)] text-white shadow-lg hover:bg-[var(--color-primary-hover)] transition-colors flex items-center justify-center"
        title="Chat with Baby Tiger"
      >
        {isOpen ? <X className="w-5 h-5" /> : <MessageCircle className="w-5 h-5" />}
      </motion.button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            className="fixed bottom-24 right-6 z-40 w-96 max-w-[calc(100vw-3rem)] h-[32rem] max-h-[calc(100vh-9rem)] rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] shadow-2xl flex flex-col overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--color-border)] flex-shrink-0">
              <BabyTiger size={28} expression="happy" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-[var(--color-text-primary)]">
                  Chat with Baby Tiger
                </p>
                <p className="text-xs text-[var(--color-text-tertiary)]">
                  Ask a question, or ask to change what you're building
                </p>
              </div>
            </div>

            {/* Messages */}
            <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
              {isLoadingHistory ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-tertiary)]" />
                </div>
              ) : messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
                  <Sparkles className="w-6 h-6 text-[var(--color-text-tertiary)]" />
                  <p className="text-xs text-[var(--color-text-tertiary)] max-w-[16rem]">
                    Ask anything about your app, or say something like "actually I
                    also want an Android app" to update your requirements.
                  </p>
                </div>
              ) : (
                messages.map((m) => (
                  <div
                    key={m.id}
                    className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap ${
                        m.role === "user"
                          ? "bg-[var(--color-primary)] text-white"
                          : "bg-[var(--color-surface-raised)] text-[var(--color-text-primary)]"
                      }`}
                    >
                      {m.content}
                      {m.intent === "requirement_change" && (
                        <p className="mt-1.5 text-xs opacity-80 flex items-center gap-1">
                          <Sparkles className="w-3 h-3" />
                          Requirements updated
                        </p>
                      )}
                    </div>
                  </div>
                ))
              )}
              {isSending && (
                <div className="flex justify-start">
                  <div className="rounded-2xl px-3 py-2 bg-[var(--color-surface-raised)]">
                    <Loader2 className="w-4 h-4 animate-spin text-[var(--color-text-tertiary)]" />
                  </div>
                </div>
              )}
            </div>

            {/* Input */}
            <div className="p-3 border-t border-[var(--color-border)] flex-shrink-0">
              <div className="flex items-end gap-2">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Type a message..."
                  rows={1}
                  className="flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)] resize-none max-h-24"
                />
                <button
                  onClick={handleSend}
                  disabled={isSending || !input.trim()}
                  className="p-2.5 rounded-xl bg-[var(--color-primary)] text-white hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex-shrink-0"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
