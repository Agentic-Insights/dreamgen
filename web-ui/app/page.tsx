"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import { Terminal, Image as ImageIcon, Settings as SettingsIcon, Sparkles, Loader2, Menu, X, Upload, Edit3 } from "lucide-react";
import { api, GenerateResponse, PluginInfo, SystemStatus, EditResponse, API_BASE } from "@/lib/api";
import Gallery from "@/components/Gallery";
import Settings from "@/components/Settings";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import galleryCache from "@/lib/cache";

export default function Home() {
  const [activeTab, setActiveTab] = useState("playground");
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
    { id: "playground", label: "Playground", icon: Sparkles },
    { id: "gallery", label: "Gallery", icon: ImageIcon },
    { id: "settings", label: "Settings", icon: SettingsIcon },
  ];

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      {/* Top Bar - Responsive */}
      <header className="bg-muted border-b border-border">
        <div className="flex items-center justify-between px-3 md:px-4 h-12 md:h-10">
          <div className="flex items-center gap-2 md:gap-3">
            {/* Mobile menu button */}
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="md:hidden p-1.5 hover:bg-background rounded-md transition-colors"
            >
              {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
            </button>

            <Image
              src="/logo_mark.png"
              alt="Agentic Insights"
              width={20}
              height={20}
              className="shrink-0"
            />
            <span className="font-semibold text-sm text-foreground hidden sm:inline">
              Continuous Image Generator
            </span>
            <span className="font-semibold text-sm text-foreground sm:hidden">
              CIG
            </span>
          </div>

          <a
            href="https://agenticinsights.com"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs hover:text-primary transition-colors flex items-center gap-1.5"
          >
            <span className="hidden sm:inline">by</span>
            <span className="font-semibold">Agentic Insights</span>
          </a>
        </div>
      </header>

      {/* Tab Bar - Responsive */}
      <div className="bg-card border-b border-border">
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
                  "hover:bg-background/50",
                  activeTab === tab.id
                    ? "border-primary text-foreground bg-background"
                    : "border-transparent text-muted-foreground"
                )}
              >
                <Icon className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Main Content Area - Responsive */}
      <main className="flex-1 overflow-hidden relative">
        <AnimatePresence mode="wait">
          {activeTab === "playground" && (
            <motion.div
              key="playground"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="h-full"
            >
              <iframe src="/playground" className="w-full h-full border-0" />
            </motion.div>
          )}

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
                    <h2 className="text-sm font-semibold text-primary">Generation Controls</h2>
                    <button
                      onClick={() => setSidebarOpen(false)}
                      className="p-1.5 hover:bg-background rounded-md"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>

                  <h2 className="text-sm font-semibold mb-4 text-primary hidden lg:block">
                    Generation Controls
                  </h2>

                  <div className="space-y-4">
                    <div>
                      <label className="text-xs text-muted-foreground">
                        Prompt (optional)
                      </label>
                      <textarea
                        className="w-full mt-1 p-2 bg-background border border-input rounded-md text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-primary/50"
                        rows={4}
                        placeholder="Leave empty for AI-generated prompt..."
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        disabled={isGenerating}
                      />
                    </div>

                    <motion.button
                      data-testid="generate-image-button"
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      className="w-full py-2.5 bg-primary text-primary-foreground rounded-md hover:opacity-90 transition-opacity font-medium text-sm disabled:opacity-50"
                      onClick={handleGenerate}
                      disabled={isGenerating}
                    >
                      {isGenerating ? (
                        <div className="flex items-center justify-center gap-2">
                          <Loader2 className="w-4 h-4 animate-spin" />
                          Generating...
                        </div>
                      ) : (
                        "Generate Image"
                      )}
                    </motion.button>

                    <div className="pt-4 border-t border-border">
                      <h3 className="text-xs font-semibold mb-2 text-muted-foreground">
                        Active Plugins
                      </h3>
                      <div className="space-y-1">
                        {plugins.map((plugin) => (
                          <label
                            key={plugin.name}
                            className="flex items-center gap-2 text-xs cursor-pointer hover:text-foreground transition-colors"
                          >
                            <input
                              type="checkbox"
                              checked={plugin.enabled}
                              onChange={() => handlePluginToggle(plugin.name)}
                              className="rounded accent-primary"
                            />
                            <span>{plugin.name}</span>
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

              {/* Right Panel - Output */}
              <div className="flex-1 flex flex-col min-h-0">
                {/* Terminal Output - Collapsible on mobile */}
                <div className={cn(
                  "border-b border-border bg-background transition-all",
                  showLogs ? "h-32 sm:h-40 lg:h-1/3" : "h-10"
                )}>
                  <div
                    className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-muted/50"
                    onClick={() => setShowLogs(!showLogs)}
                  >
                    <div className="flex items-center gap-2">
                      <Terminal className="w-4 h-4 text-primary" />
                      <span className="text-xs font-semibold text-muted-foreground">Output</span>
                    </div>
                    <motion.div
                      animate={{ rotate: showLogs ? 180 : 0 }}
                      className="text-muted-foreground"
                    >
                      ▼
                    </motion.div>
                  </div>

                  {showLogs && (
                    <div className="px-3 pb-3 overflow-y-auto h-[calc(100%-2.5rem)]">
                      <div className="font-mono text-xs space-y-1">
                        {logs.map((log, i) => (
                          <div
                            key={i}
                            className={cn(
                              "break-all",
                              log.includes('[ERROR]') ? 'text-destructive' : 'text-primary'
                            )}
                          >
                            {log}
                          </div>
                        ))}
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
                        src={`${API_BASE}${currentImage.image_path}`}
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

      {/* Status Bar - Responsive */}
      <footer className="h-6 bg-muted border-t border-border">
        <div className="h-full flex items-center px-2 sm:px-3 text-xs text-muted-foreground">
          <span className="truncate">
            {status?.status === 'ready' ? '● Ready' : '○ Connecting...'}
          </span>
          <div className="flex-1" />
          <div className="flex items-center gap-2 text-xs">
            <span className="hidden sm:inline">
              {status ? 'API ✓' : 'API ✗'}
            </span>
            <div className="w-px h-3 bg-border hidden sm:block" />
            <span>GPU: {status?.gpu_available ? '✓' : '✗'}</span>
            <div className="w-px h-3 bg-border hidden md:block" />
            <span className="hidden md:inline truncate">
              {status?.backend || 'Unknown'}
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
