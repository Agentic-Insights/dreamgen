"use client";
/* eslint-disable @next/next/no-img-element */

import { useEffect, useRef, useState } from "react";
import {
  Sparkles,
  Loader2,
  Settings as SettingsIcon,
  Wand2,
  History,
  ChevronRight,
  ChevronDown,
  Image as ImageIcon,
  Sliders
} from "lucide-react";
import { api, GenerateResponse, PluginInfo, API_BASE } from "@/lib/api";
import { motion, AnimatePresence } from "framer-motion";
import MetaPromptModal from "@/components/MetaPromptModal";
import AdvancedControls from "@/components/AdvancedControls";
import TaskProgress from "@/components/TaskProgress";
import {
  createClientRequestId,
  getFallbackProgress,
  getTaskProgressUpdate,
  INITIAL_IMAGE_PROGRESS,
  INITIAL_PROMPT_PROGRESS,
  type ProgressSnapshot,
} from "@/lib/task-progress";

export default function Playground() {
  // State management
  const [metaPrompt, setMetaPrompt] = useState("");
  const [generatedPrompt, setGeneratedPrompt] = useState("");
  const [finalPrompt, setFinalPrompt] = useState("");
  const [promptError, setPromptError] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [isGeneratingPrompt, setIsGeneratingPrompt] = useState(false);
  const [isGeneratingImage, setIsGeneratingImage] = useState(false);
  const [promptProgress, setPromptProgress] = useState<ProgressSnapshot | null>(null);
  const [imageProgress, setImageProgress] = useState<ProgressSnapshot | null>(null);
  const [currentImage, setCurrentImage] = useState<GenerateResponse | null>(null);
  const [recentGenerations, setRecentGenerations] = useState<GenerateResponse[]>([]);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [showMetaPromptModal, setShowMetaPromptModal] = useState(false);
  const [expandedSections, setExpandedSections] = useState({
    prompt: true,
    plugins: false,
    advanced: false,
    history: true
  });
  const [seed, setSeed] = useState<number | null>(null);
  const promptRequestIdRef = useRef<string | null>(null);
  const imageRequestIdRef = useRef<string | null>(null);
  const promptResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const imageResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    loadPlugins();
  }, []);

  useEffect(() => {
    const unsubscribe = api.subscribeWebSocket((data) => {
      const nextPromptProgress = getTaskProgressUpdate(
        data,
        "prompt_generation",
        promptRequestIdRef.current
      );
      if (nextPromptProgress) {
        setPromptProgress((prev) =>
          prev && prev.progress > nextPromptProgress.progress ? prev : nextPromptProgress
        );
      }

      const nextImageProgress = getTaskProgressUpdate(
        data,
        "image_generation",
        imageRequestIdRef.current
      );
      if (nextImageProgress) {
        setImageProgress((prev) =>
          prev && prev.progress > nextImageProgress.progress ? prev : nextImageProgress
        );
      }

      if (typeof data !== "object" || data === null || !("type" in data)) return;

      const msg = data as Record<string, unknown>;
      if (
        msg.type === "generation_error" &&
        msg.client_request_id === imageRequestIdRef.current
      ) {
        setImageError(String(msg.error ?? "Failed to generate image"));
        setIsGeneratingImage(false);
        setImageProgress(null);
        imageRequestIdRef.current = null;
      }
    });

    return () => {
      unsubscribe();
      if (promptResetTimeoutRef.current) clearTimeout(promptResetTimeoutRef.current);
      if (imageResetTimeoutRef.current) clearTimeout(imageResetTimeoutRef.current);
    };
  }, []);

  useEffect(() => {
    if (!isGeneratingPrompt || !promptProgress || promptProgress.progress >= 96) return;

    const timeoutId = setTimeout(() => {
      setPromptProgress((prev) =>
        prev ? getFallbackProgress("prompt_generation", prev) : prev
      );
    }, 1800);

    return () => clearTimeout(timeoutId);
  }, [isGeneratingPrompt, promptProgress]);

  useEffect(() => {
    if (!isGeneratingImage || !imageProgress || imageProgress.progress >= 96) return;

    const timeoutId = setTimeout(() => {
      setImageProgress((prev) =>
        prev ? getFallbackProgress("image_generation", prev) : prev
      );
    }, 2500);

    return () => clearTimeout(timeoutId);
  }, [isGeneratingImage, imageProgress]);

  const loadPlugins = async () => {
    try {
      const pluginList = await api.getPlugins();
      setPlugins(pluginList);
    } catch (error) {
      console.error('Failed to load plugins:', error);
    }
  };

  const handleGeneratePrompt = async () => {
    const clientRequestId = createClientRequestId("prompt");
    promptRequestIdRef.current = clientRequestId;
    if (promptResetTimeoutRef.current) clearTimeout(promptResetTimeoutRef.current);
    setIsGeneratingPrompt(true);
    setPromptError(null);
    setPromptProgress(INITIAL_PROMPT_PROGRESS);
    try {
      const response = await api.generatePrompt(metaPrompt || undefined, clientRequestId);

      setGeneratedPrompt(response.prompt);
      setFinalPrompt(response.prompt);
      setPromptProgress({
        progress: 100,
        title: "Prompt ready",
        detail: "The generated prompt is ready to edit or use directly.",
      });
      if (promptResetTimeoutRef.current) clearTimeout(promptResetTimeoutRef.current);
      promptResetTimeoutRef.current = setTimeout(() => {
        setPromptProgress(null);
      }, 900);
    } catch (error) {
      console.error('Failed to generate prompt:', error);
      setPromptError(error instanceof Error ? error.message : 'Failed to generate prompt');
      setPromptProgress(null);
    } finally {
      promptRequestIdRef.current = null;
      setIsGeneratingPrompt(false);
    }
  };

  const handleGenerateImage = async () => {
    if (!finalPrompt.trim()) return;

    const clientRequestId = createClientRequestId("image");
    imageRequestIdRef.current = clientRequestId;
    if (imageResetTimeoutRef.current) clearTimeout(imageResetTimeoutRef.current);
    setIsGeneratingImage(true);
    setImageError(null);
    setImageProgress(INITIAL_IMAGE_PROGRESS);
    try {
      const response = await api.generate({
        prompt: finalPrompt,
        enable_plugins: true,
        seed: seed ?? undefined,
        client_request_id: clientRequestId,
      });

      setCurrentImage(response);

      // Add to recent generations (keep last 10)
      setRecentGenerations(prev => [response, ...prev].slice(0, 10));
      setImageProgress({
        progress: 100,
        title: "Image ready",
        detail: "The generated image is saved and ready to review.",
      });
      if (imageResetTimeoutRef.current) clearTimeout(imageResetTimeoutRef.current);
      imageResetTimeoutRef.current = setTimeout(() => {
        setImageProgress(null);
      }, 1200);
    } catch (error) {
      console.error('Failed to generate image:', error);
      setImageError(error instanceof Error ? error.message : 'Failed to generate image');
      setImageProgress(null);
    } finally {
      imageRequestIdRef.current = null;
      setIsGeneratingImage(false);
    }
  };

  const handlePluginToggle = async (pluginName: string) => {
    try {
      await api.togglePlugin(pluginName);
      await loadPlugins();
    } catch (error) {
      console.error('Failed to toggle plugin:', error);
    }
  };

  const toggleSection = (section: keyof typeof expandedSections) => {
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
  };

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      {/* Main Content */}
      <main className="flex-1 flex overflow-hidden">
        {/* Left Panel - Prompt Controls */}
        <div className="w-96 border-r border-border bg-card flex flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {/* Prompt Generation Section */}
            <div className="border border-border rounded-lg overflow-hidden">
              <button
                onClick={() => toggleSection('prompt')}
                className="w-full flex items-center justify-between p-3 hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Wand2 className="w-4 h-4 text-primary" />
                  <span className="font-medium text-sm">Prompt Generation</span>
                </div>
                {expandedSections.prompt ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
              </button>

              <AnimatePresence>
                {expandedSections.prompt && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="border-t border-border"
                  >
                    <div className="p-3 space-y-3">
                      {/* Meta Prompt Button */}
                      <button
                        onClick={() => setShowMetaPromptModal(true)}
                        className="w-full px-3 py-2 bg-muted hover:bg-muted/80 rounded-md text-sm flex items-center justify-between transition-colors"
                      >
                        <span>Edit Meta Prompt</span>
                        <SettingsIcon className="w-3.5 h-3.5" />
                      </button>

                      {/* Generate Prompt Button */}
                      <button
                        onClick={handleGeneratePrompt}
                        disabled={isGeneratingPrompt}
                        className="w-full py-2 bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-opacity font-medium text-sm disabled:opacity-50"
                      >
                        {isGeneratingPrompt ? (
                          <div className="flex items-center justify-center gap-2">
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Generating...
                          </div>
                        ) : (
                          <div className="flex items-center justify-center gap-2">
                            <Sparkles className="w-4 h-4" />
                            Generate Prompt
                          </div>
                        )}
                      </button>

                      {isGeneratingPrompt && promptProgress && (
                        <TaskProgress progress={promptProgress} compact />
                      )}

                      {promptError && (
                        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                          {promptError}
                        </div>
                      )}

                      {/* Generated Prompt Display */}
                      {generatedPrompt && (
                        <div className="space-y-2">
                          <label className="text-xs text-muted-foreground">Generated Prompt:</label>
                          <div className="p-2 bg-background border border-border rounded-md text-xs">
                            {generatedPrompt}
                          </div>
                        </div>
                      )}

                      {/* Final Prompt Editor */}
                      <div className="space-y-2">
                        <label className="text-xs text-muted-foreground">Final Prompt (editable):</label>
                        <textarea
                          value={finalPrompt}
                          onChange={(e) => setFinalPrompt(e.target.value)}
                          className="w-full p-2 bg-background border border-input rounded-md text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-primary/50"
                          rows={4}
                          placeholder="Edit the generated prompt or write your own..."
                        />
                      </div>

                      {/* Generate Image Button */}
                      <button
                        onClick={handleGenerateImage}
                        disabled={isGeneratingImage || !finalPrompt.trim()}
                        className="w-full py-2.5 bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-opacity font-medium text-sm disabled:opacity-50"
                      >
                        {isGeneratingImage ? (
                          <div className="flex items-center justify-center gap-2">
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Generating Image...
                          </div>
                        ) : (
                          <div className="flex items-center justify-center gap-2">
                            <ImageIcon className="w-4 h-4" />
                            Generate Image
                          </div>
                        )}
                      </button>

                      {isGeneratingImage && imageProgress && (
                        <TaskProgress progress={imageProgress} compact />
                      )}

                      {imageError && (
                        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                          {imageError}
                        </div>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* Advanced Controls Section */}
            <div className="border border-border rounded-lg overflow-hidden">
              <button
                onClick={() => toggleSection('advanced')}
                className="w-full flex items-center justify-between p-3 hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Sliders className="w-4 h-4 text-primary" />
                  <span className="font-medium text-sm">Advanced Settings</span>
                </div>
                {expandedSections.advanced ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
              </button>

              <AnimatePresence>
                {expandedSections.advanced && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="border-t border-border"
                  >
                    <div className="p-3">
                      <AdvancedControls seed={seed} onSeedChange={setSeed} />
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* Plugin Configuration Section */}
            <div className="border border-border rounded-lg overflow-hidden">
              <button
                onClick={() => toggleSection('plugins')}
                className="w-full flex items-center justify-between p-3 hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <SettingsIcon className="w-4 h-4 text-primary" />
                  <span className="font-medium text-sm">Plugin Configuration</span>
                </div>
                {expandedSections.plugins ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
              </button>

              <AnimatePresence>
                {expandedSections.plugins && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="border-t border-border"
                  >
                    <div className="p-3 space-y-2">
                      {(plugins || []).map((plugin) => (
                        <label
                          key={plugin.name}
                          className="flex items-center gap-2 p-2 hover:bg-muted/50 rounded-md cursor-pointer transition-colors"
                        >
                          <input
                            type="checkbox"
                            checked={plugin.enabled}
                            onChange={() => handlePluginToggle(plugin.name)}
                            className="rounded accent-primary"
                          />
                          <div className="flex-1">
                            <div className="text-sm font-medium">{plugin.name}</div>
                            <div className="text-xs text-muted-foreground">{plugin.description}</div>
                          </div>
                        </label>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>

        {/* Center Panel - Image Display */}
        <div className="flex-1 flex items-center justify-center p-8 bg-muted/30">
          <AnimatePresence mode="wait">
            {isGeneratingImage ? (
              <motion.div
                key="loading"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                className="w-full px-6"
              >
                <TaskProgress progress={imageProgress ?? INITIAL_IMAGE_PROGRESS} />
              </motion.div>
            ) : currentImage ? (
              <motion.div
                key={currentImage.id}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                className="max-w-full max-h-full"
              >
                <img
                  src={`${API_BASE}${currentImage.image_path}`}
                  alt="Generated image"
                  className="max-w-full max-h-[calc(100vh-12rem)] object-contain rounded-lg shadow-2xl"
                />
                <p className="text-xs text-muted-foreground mt-4 text-center max-w-2xl mx-auto">
                  {currentImage.prompt}
                </p>
              </motion.div>
            ) : (
              <div className="text-center">
                <ImageIcon className="w-16 h-16 text-muted-foreground/30 mx-auto mb-4" />
                <p className="text-sm text-muted-foreground">No image generated yet</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Generate a prompt and create your first image
                </p>
              </div>
            )}
          </AnimatePresence>
        </div>

        {/* Right Panel - History */}
        <div className="w-80 border-l border-border bg-card flex flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto p-4">
            <div className="border border-border rounded-lg overflow-hidden">
              <button
                onClick={() => toggleSection('history')}
                className="w-full flex items-center justify-between p-3 hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <History className="w-4 h-4 text-primary" />
                  <span className="font-medium text-sm">Recent Generations</span>
                </div>
                {expandedSections.history ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
              </button>

              <AnimatePresence>
                {expandedSections.history && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    className="border-t border-border"
                  >
                    <div className="p-3 space-y-2">
                      {recentGenerations.length > 0 ? (
                        recentGenerations.map((gen) => (
                          <button
                            key={gen.id}
                            onClick={() => {
                              setCurrentImage(gen);
                              setFinalPrompt(gen.prompt);
                            }}
                            className="w-full p-2 border border-border rounded-md hover:bg-muted/50 transition-colors text-left"
                          >
                            <img
                              src={`${API_BASE}${gen.image_path}`}
                              alt="Thumbnail"
                              className="w-full h-24 object-cover rounded mb-2"
                            />
                            <p className="text-xs text-muted-foreground line-clamp-2">
                              {gen.prompt}
                            </p>
                          </button>
                        ))
                      ) : (
                        <p className="text-xs text-muted-foreground text-center py-4">
                          No generations yet
                        </p>
                      )}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>
      </main>

      {/* Meta Prompt Modal */}
      <MetaPromptModal
        isOpen={showMetaPromptModal}
        onClose={() => setShowMetaPromptModal(false)}
        metaPrompt={metaPrompt}
        onSave={setMetaPrompt}
      />
    </div>
  );
}
