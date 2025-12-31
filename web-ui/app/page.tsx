"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import { Terminal, Image as ImageIcon, Settings as SettingsIcon, Sparkles, Loader2, Menu, X, Upload, Edit3 } from "lucide-react";
import { api, getImageUrl, GenerateResponse, PluginInfo, SystemStatus, EditResponse } from "@/lib/api";
import Gallery from "@/components/Gallery";
import Settings from "@/components/Settings";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import galleryCache from "@/lib/cache";

export default function Home() {
  const [activeTab, setActiveTab] = useState("generate");
  const [prompt, setPrompt] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [currentImage, setCurrentImage] = useState<GenerateResponse | null>(null);
  const [logs, setLogs] = useState<string[]>(["$ Ready to generate..."]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [generationStatus, setGenerationStatus] = useState<string>("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [showLogs, setShowLogs] = useState(true);

  // Image editing state
  const [editMode, setEditMode] = useState<"generate" | "edit">("generate");
  const [editPrompt, setEditPrompt] = useState("");
  const [editStrength, setEditStrength] = useState(0.8);
  const [isEditing, setIsEditing] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [currentEdit, setCurrentEdit] = useState<EditResponse | null>(null);
  const [dragActive, setDragActive] = useState(false);

  useEffect(() => {
    // Fetch initial status
    api.getStatus().then(setStatus).catch(console.error);
    api.getPlugins().then(setPlugins).catch(console.error);

    // Connect WebSocket for real-time updates
    api.connectWebSocket((data) => {
      // Type guard for websocket data
      if (typeof data === 'object' && data !== null && 'type' in data) {
        const msg = data as Record<string, unknown>;
        if (msg.type === 'generation_started') {
          addLog(`Generation started: ${msg.id}`);
        } else if (msg.type === 'prompt_generated') {
          addLog(`Prompt: ${msg.prompt}`);
        } else if (msg.type === 'model_loading') {
          addLog(`Loading model: ${msg.message}`);
          setGenerationStatus("Loading Flux model...");
        } else if (msg.type === 'generation_completed') {
          addLog(`Image generated: ${msg.image_path}`);
          setGenerationStatus("");
        } else if (msg.type === 'generation_error') {
          addLog(`Error: ${msg.error}`, 'error');
          setGenerationStatus("");
          setIsGenerating(false);
        } else if (msg.type === 'model_download_started') {
          addLog(`Model download started: ${msg.model_id}`);
        } else if (msg.type === 'model_download_completed') {
          addLog(`Model download completed: ${msg.model_id}`);
        } else if (msg.type === 'model_download_error') {
          addLog(`Model download failed: ${msg.model_id} - ${msg.error}`, 'error');
        }
      }
    });

    return () => {
      api.disconnectWebSocket();
    };
  }, []);

  const addLog = (message: string, type: 'info' | 'error' = 'info') => {
    const timestamp = new Date().toLocaleTimeString();
    const prefix = type === 'error' ? '[ERROR]' : '[INFO]';
    setLogs(prev => [...prev, `${timestamp} ${prefix} ${message}`]);
  };

  const handleGenerate = async () => {
    setIsGenerating(true);
    addLog("Starting image generation...");

    try {
      const response = await api.generate({
        prompt: prompt || undefined,
        enable_plugins: true,
      });

      setCurrentImage(response);
      addLog(`Success! Image saved as: ${response.image_path}`);
      setGenerationStatus("");

      // Clear gallery cache when new image is generated
      await galleryCache.clear();
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      addLog(`Generation failed: ${errorMsg}`, 'error');
      setGenerationStatus("");
      if (errorMsg.includes("memory") || errorMsg.includes("Memory")) {
        addLog("💡 Tip: The Flux model requires significant RAM/VRAM. Consider using a GPU-enabled system.", 'error');
      }
    } finally {
      setIsGenerating(false);
      setGenerationStatus("");
    }
  };

  const handlePluginToggle = async (pluginName: string) => {
    try {
      await api.togglePlugin(pluginName);
      const updatedPlugins = await api.getPlugins();
      setPlugins(updatedPlugins);
    } catch (error) {
      console.error('Failed to toggle plugin:', error);
    }
  };

  const tabs = [
    { id: "generate", label: "Generate", icon: Sparkles },
    { id: "gallery", label: "Gallery", icon: ImageIcon },
    { id: "settings", label: "Settings", icon: SettingsIcon },
  ];

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      {/* Top Bar - Terminal Style */}
      <header className="bg-background border-b border-border">
        <div className="flex items-center justify-between px-3 md:px-4 h-12 md:h-10">
          <div className="flex items-center gap-2 md:gap-3">
            {/* Mobile menu button */}
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="md:hidden p-1.5 hover:bg-card transition-colors"
            >
              {sidebarOpen ? <X className="w-5 h-5 text-primary" /> : <Menu className="w-5 h-5 text-primary" />}
            </button>

            <Image
              src="/logo_mark.png"
              alt="Agentic Insights"
              width={20}
              height={20}
              className="shrink-0"
            />
            <span className="font-bold text-sm text-primary tracking-wider hidden sm:inline">
              DREAMGEN
            </span>
            <span className="text-muted-foreground text-xs hidden md:inline">
              {"//"}<span>image_generator</span>
            </span>
          </div>

          <a
            href="https://agenticinsights.com"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-muted-foreground hover:text-primary transition-colors flex items-center gap-1.5 underline-animate"
          >
            <span className="hidden sm:inline text-muted-foreground">&gt;</span>
            <span className="font-medium">AGENTIC_INSIGHTS</span>
          </a>
        </div>
      </header>

      {/* Tab Bar - Terminal Style */}
      <div className="bg-background border-b border-border">
        <div className="flex overflow-x-auto scrollbar-none">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                data-testid={`tab-${tab.id}`}
                onClick={() => {
                  setActiveTab(tab.id);
                  setSidebarOpen(false);
                }}
                className={cn(
                  "px-3 md:px-4 py-2 text-sm border-b-2 transition-all whitespace-nowrap flex items-center gap-2",
                  "hover:bg-card",
                  activeTab === tab.id
                    ? "border-primary text-primary bg-card"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                <Icon className="w-3.5 h-3.5" />
                <span className="hidden sm:inline uppercase tracking-wide text-xs">{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Main Content Area - Responsive */}
      <main className="flex-1 overflow-hidden relative">
        <AnimatePresence mode="wait">
          {activeTab === "generate" && (
            <motion.div
              key="generate"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="h-full flex flex-col lg:flex-row"
            >
              {/* Sidebar/Controls - Mobile Overlay or Desktop Sidebar */}
              <div className={cn(
                "lg:w-80 border-border bg-card lg:border-r",
                "absolute lg:relative inset-y-0 left-0 z-30 lg:z-auto",
                "w-full sm:w-80 lg:w-80",
                "transform transition-transform lg:transform-none",
                sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
              )}>
                <div className="h-full flex flex-col p-4 overflow-y-auto">
                  <div className="flex items-center justify-between mb-4 lg:hidden">
                    <h2 className="text-xs font-bold text-primary uppercase tracking-wider">&gt; Controls</h2>
                    <button
                      onClick={() => setSidebarOpen(false)}
                      className="p-1.5 hover:bg-background"
                    >
                      <X className="w-4 h-4 text-primary" />
                    </button>
                  </div>

                  <h2 className="text-xs font-bold mb-4 text-primary uppercase tracking-wider hidden lg:block">
                    &gt; Controls
                  </h2>

                  <div className="space-y-4">
                    <div>
                      <label className="text-xs text-muted-foreground uppercase tracking-wide">
                        Prompt (optional)
                      </label>
                      <textarea
                        className="w-full mt-1 p-2 bg-background border border-border text-sm font-mono resize-none focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary placeholder:text-muted-foreground/50"
                        rows={4}
                        placeholder="$ enter prompt or leave empty..."
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        disabled={isGenerating}
                      />
                    </div>

                    <motion.button
                      data-testid="generate-image-button"
                      whileHover={{ scale: 1.01 }}
                      whileTap={{ scale: 0.99 }}
                      className="w-full py-2.5 bg-primary text-primary-foreground hover:bg-primary/90 transition-colors font-bold text-sm uppercase tracking-wider disabled:opacity-50 disabled:cursor-not-allowed"
                      onClick={handleGenerate}
                      disabled={isGenerating}
                    >
                      {isGenerating ? (
                        <div className="flex items-center justify-center gap-2">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          PROCESSING...
                        </div>
                      ) : (
                        "GENERATE"
                      )}
                    </motion.button>

                    <div className="pt-4 border-t border-border">
                      <h3 className="text-xs font-bold mb-2 text-muted-foreground uppercase tracking-wider">
                        Plugins
                      </h3>
                      <div className="space-y-1">
                        {plugins.map((plugin) => (
                          <label
                            key={plugin.name}
                            className="flex items-center gap-2 text-xs cursor-pointer hover:text-primary transition-colors"
                          >
                            <input
                              type="checkbox"
                              checked={plugin.enabled}
                              onChange={() => handlePluginToggle(plugin.name)}
                              className="accent-primary"
                            />
                            <span className="font-mono">{plugin.name}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Mobile overlay backdrop */}
              {sidebarOpen && (
                <div
                  className="fixed inset-0 bg-black/50 z-20 lg:hidden"
                  onClick={() => setSidebarOpen(false)}
                />
              )}

              {/* Mobile Floating Generate Button */}
              <motion.button
                data-testid="mobile-generate-button"
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                className="lg:hidden fixed bottom-20 right-4 z-10 w-14 h-14 bg-primary text-primary-foreground rounded-full shadow-lg flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
                onClick={handleGenerate}
                disabled={isGenerating}
              >
                {isGenerating ? (
                  <Loader2 className="w-6 h-6 animate-spin" />
                ) : (
                  <Sparkles className="w-6 h-6" />
                )}
              </motion.button>

              {/* Right Panel - Output */}
              <div className="flex-1 flex flex-col min-h-0">
                {/* Terminal Output - Collapsible on mobile */}
                <div className={cn(
                  "border-b border-border bg-background transition-all",
                  showLogs ? "h-32 sm:h-40 lg:h-1/3" : "h-10"
                )}>
                  <div
                    className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-card"
                    onClick={() => setShowLogs(!showLogs)}
                  >
                    <div className="flex items-center gap-2">
                      <Terminal className="w-4 h-4 text-primary" />
                      <span className="text-xs font-bold text-primary uppercase tracking-wider">&gt; Output</span>
                    </div>
                    <motion.div
                      animate={{ rotate: showLogs ? 180 : 0 }}
                      className="text-muted-foreground text-xs"
                    >
                      ▼
                    </motion.div>
                  </div>

                  {showLogs && (
                    <div className="px-3 pb-3 overflow-y-auto h-[calc(100%-2.5rem)]">
                      <div className="font-mono text-xs space-y-0.5">
                        {logs.map((log, i) => (
                          <div
                            key={i}
                            className={cn(
                              "break-all",
                              log.includes('[ERROR]') ? 'text-destructive' : 'text-primary/80'
                            )}
                          >
                            {log}
                          </div>
                        ))}
                        <span className="text-primary animate-blink">_</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* Image Display - Responsive */}
                <div className="flex-1 flex items-center justify-center p-4 sm:p-6 lg:p-8">
                  {isGenerating ? (
                    <motion.div
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className="text-center"
                    >
                      <Loader2 className="w-12 h-12 sm:w-16 sm:h-16 text-primary animate-spin mx-auto mb-4" />
                      <p className="text-sm text-foreground">
                        {generationStatus || "Generating image..."}
                      </p>
                      <p className="text-xs text-muted-foreground mt-2">
                        {generationStatus.includes("Loading")
                          ? "First time model loading can take several minutes"
                          : "This may take a moment"}
                      </p>
                      <div className="mt-4 max-w-xs sm:max-w-md mx-auto">
                        <div className="h-1 bg-muted rounded-full overflow-hidden">
                          <motion.div
                            className="h-full bg-primary"
                            animate={{ x: ["-100%", "100%"] }}
                            transition={{ repeat: Infinity, duration: 1.5, ease: "linear" }}
                            style={{ width: "30%" }}
                          />
                        </div>
                      </div>
                    </motion.div>
                  ) : currentImage ? (
                    <motion.div
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      className="max-w-full max-h-full"
                    >
                      <img
                        src={getImageUrl(currentImage.image_path)}
                        alt="Generated image"
                        className="max-w-full max-h-full object-contain rounded-lg shadow-2xl"
                      />
                      <p className="text-xs text-muted-foreground mt-4 text-center max-w-lg mx-auto">
                        {currentImage.prompt}
                      </p>
                    </motion.div>
                  ) : (
                    <div className="text-center">
                      <ImageIcon className="w-12 h-12 sm:w-16 sm:h-16 text-muted-foreground/30 mx-auto mb-4" />
                      <p className="text-sm text-muted-foreground">No image generated yet</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        {sidebarOpen ? "Configure and generate" : "Click Generate to start"}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          )}

          {activeTab === "gallery" && (
            <motion.div
              key="gallery"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="h-full"
            >
              <Gallery />
            </motion.div>
          )}

          {activeTab === "settings" && (
            <motion.div
              key="settings"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="h-full"
            >
              <Settings systemStatus={status} />
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* Status Bar - Terminal Style */}
      <footer className="h-6 bg-background border-t border-border">
        <div className="h-full flex items-center px-2 sm:px-3 text-xs font-mono">
          <span className={cn(
            "truncate",
            status?.status === 'ready' ? 'text-primary' : 'text-muted-foreground'
          )}>
            {status?.status === 'ready' ? '[READY]' : '[CONNECTING...]'}
          </span>
          <div className="flex-1" />
          <div className="flex items-center gap-3 text-xs">
            <span className={cn(
              "hidden sm:inline",
              status ? 'text-primary' : 'text-destructive'
            )}>
              API:{status ? 'OK' : 'ERR'}
            </span>
            <span className="text-border hidden sm:inline">|</span>
            <span className={status?.gpu_available ? 'text-primary' : 'text-muted-foreground'}>
              GPU:{status?.gpu_available ? 'ON' : 'OFF'}
            </span>
            <span className="text-border hidden md:inline">|</span>
            <span className="hidden md:inline truncate text-muted-foreground">
              {status?.backend || 'unknown'}
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
