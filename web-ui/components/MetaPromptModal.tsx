"use client";

import { useState, useEffect } from "react";
import { X, Save, RotateCcw } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface MetaPromptModalProps {
  isOpen: boolean;
  onClose: () => void;
  metaPrompt: string;
  onSave: (prompt: string) => void;
}

const DEFAULT_META_PROMPT = `You are a creative prompt generator for image generation.
Generate unique and imaginative prompts that would inspire beautiful AI-generated images.

IMPORTANT: Prompts MUST be concise and fit within 77 tokens (approximately 60 words).
IMPORTANT: Do not have a preamble or explain the prompt, output ONLY the prompt itself.

Focus on vivid, impactful descriptions using fewer, carefully chosen words.`;

export default function MetaPromptModal({ isOpen, onClose, metaPrompt, onSave }: MetaPromptModalProps) {
  const [editedPrompt, setEditedPrompt] = useState(metaPrompt || DEFAULT_META_PROMPT);

  useEffect(() => {
    if (isOpen && !metaPrompt) {
      setEditedPrompt(DEFAULT_META_PROMPT);
    } else if (isOpen) {
      setEditedPrompt(metaPrompt);
    }
  }, [isOpen, metaPrompt]);

  const handleSave = () => {
    onSave(editedPrompt);
    onClose();
  };

  const handleReset = () => {
    setEditedPrompt(DEFAULT_META_PROMPT);
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50"
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="bg-background border border-border rounded-lg shadow-2xl max-w-3xl w-full max-h-[80vh] flex flex-col">
              {/* Header */}
              <div className="flex items-center justify-between p-4 border-b border-border">
                <div>
                  <h2 className="text-lg font-semibold">Edit Meta Prompt</h2>
                  <p className="text-xs text-muted-foreground mt-1">
                    This system prompt guides how Ollama generates image prompts
                  </p>
                </div>
                <button
                  onClick={onClose}
                  className="p-2 hover:bg-muted rounded-md transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Content */}
              <div className="flex-1 overflow-y-auto p-4">
                <textarea
                  value={editedPrompt}
                  onChange={(e) => setEditedPrompt(e.target.value)}
                  className="w-full h-full min-h-[300px] p-3 bg-muted border border-input rounded-md text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-primary/50"
                  placeholder="Enter your meta prompt..."
                />
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between p-4 border-t border-border">
                <button
                  onClick={handleReset}
                  className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors flex items-center gap-2"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  Reset to Default
                </button>
                <div className="flex gap-2">
                  <button
                    onClick={onClose}
                    className="px-4 py-2 text-sm border border-border rounded-md hover:bg-muted transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleSave}
                    className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-opacity flex items-center gap-2"
                  >
                    <Save className="w-3.5 h-3.5" />
                    Save Changes
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
