"use client";

import { useCallback, useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Settings as SettingsIcon,
  Download,
  CheckCircle,
  AlertCircle,
  Loader2,
  Eye,
  EyeOff,
  Server,
  Database,
  Key,
  Cpu,
  HardDrive,
  RefreshCw,
  ArrowUp,
  ArrowDown,
  SlidersHorizontal,
  Sparkles,
  Brain,
  Image as ImageIcon,
  ArrowRight,
} from "lucide-react";
import {
  api,
  ModelStatus,
  ModelInfo,
  HFTokenStatus,
  SystemStatus,
  OllamaModelsResponse,
  PluginInfo,
  GenerationConfig,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface SettingsProps {
  systemStatus: SystemStatus | null;
  onRuntimeChange?: () => Promise<void> | void;
}

const IMAGE_BACKEND_OPTIONS = [
  { id: "auto", label: "Auto", description: "Use the best ready local backend." },
  { id: "zimage", label: "Z-Image", description: "Use the Z-Image stack and local LoRAs." },
  { id: "qwen", label: "Qwen-Image", description: "Use Qwen-Image for text-rich posters, signs, and bilingual typography." },
  { id: "ernie", label: "ERNIE-Image", description: "Use ERNIE-Image-Turbo for 8-step prompt-enhanced multilingual text rendering." },
  { id: "ollama", label: "Ollama Image", description: "Use an image-capable Ollama model over the local Ollama host API." },
  { id: "flux", label: "FLUX", description: "Prefer the FLUX transformer path." },
  { id: "small", label: "Small SD", description: "Use the lightweight public fallback." },
  { id: "turbo", label: "Turbo", description: "Run the fast SD Turbo backend." },
  { id: "smoke", label: "Smoke", description: "Use the tiny smoke-test model." },
  { id: "mock", label: "Mock", description: "Generate placeholders without loading a model." },
] as const;

export default function Settings({ systemStatus, onRuntimeChange }: SettingsProps) {
  const [activeSection, setActiveSection] = useState("models");
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [modelStatusError, setModelStatusError] = useState(false);
  const [generationConfig, setGenerationConfig] = useState<GenerationConfig | null>(null);
  const [loadingGenerationConfig, setLoadingGenerationConfig] = useState(false);
  const [hfTokenStatus, setHFTokenStatus] = useState<HFTokenStatus | null>(null);
  const [hfToken, setHFToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [downloadingModels, setDownloadingModels] = useState<Set<string>>(new Set());
  const [ollamaModels, setOllamaModels] = useState<OllamaModelsResponse | null>(null);
  const [loadingOllama, setLoadingOllama] = useState(false);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [loadingPlugins, setLoadingPlugins] = useState(false);
  const [pluginsError, setPluginsError] = useState(false);

  const notifyRuntimeChange = useCallback(async () => {
    await onRuntimeChange?.();
  }, [onRuntimeChange]);

  useEffect(() => {
    // Older builds briefly mirrored the HF token into browser storage. Remove
    // that stale copy and keep the browser out of credential persistence.
    if (typeof window !== "undefined") {
      window.localStorage.removeItem("hf_token");
    }
    loadModelStatus();
    loadGenerationConfig();
    loadHFTokenStatus();
    loadOllamaModels();
    loadPlugins();
  }, []);

  useEffect(() => {
    // Handle WebSocket messages for model download progress
    const handleWebSocketMessage = (data: unknown) => {
      if (typeof data === 'object' && data !== null && 'type' in data) {
        const msg = data as Record<string, unknown>;

        if (msg.type === 'model_download_started') {
          setDownloadingModels(prev => new Set(prev).add(msg.model_id as string));
        } else if (msg.type === 'model_download_completed' || msg.type === 'model_download_error') {
          setDownloadingModels(prev => {
            const newSet = new Set(prev);
            newSet.delete(msg.model_id as string);
            return newSet;
          });
          loadModelStatus(); // Refresh model status
        }
      }
    };

    const unsubscribe = api.subscribeWebSocket(handleWebSocketMessage);

    return () => {
      unsubscribe();
    };
  }, []);

  const loadModelStatus = async () => {
    setModelStatusError(false);
    try {
      const status = await api.getModelStatus();
      setModelStatus(status);
    } catch (error) {
      console.error('Failed to load model status:', error);
      setModelStatusError(true);
    }
  };

  const loadGenerationConfig = async () => {
    setLoadingGenerationConfig(true);
    try {
      const currentConfig = await api.getGenerationConfig();
      setGenerationConfig(currentConfig);
    } catch (error) {
      console.error('Failed to load generation config:', error);
      setMessage({ type: 'error', text: 'Failed to load generation settings' });
    } finally {
      setLoadingGenerationConfig(false);
    }
  };

  const loadHFTokenStatus = async () => {
    try {
      const status = await api.getHFTokenStatus();
      setHFTokenStatus(status);
    } catch (error) {
      console.error('Failed to load HF token status:', error);
    }
  };

  const loadOllamaModels = async () => {
    setLoadingOllama(true);
    try {
      const models = await api.getOllamaModels();
      setOllamaModels(models);
    } catch (error) {
      console.error('Failed to load Ollama models:', error);
      setMessage({ type: 'error', text: 'Failed to load Ollama models. Is Ollama running?' });
    } finally {
      setLoadingOllama(false);
    }
  };

  const loadPlugins = async () => {
    setLoadingPlugins(true);
    setPluginsError(false);
    try {
      const pluginList = await api.getPlugins();
      setPlugins(pluginList);
    } catch (error) {
      console.error('Failed to load plugins:', error);
      setPluginsError(true);
      setMessage({ type: 'error', text: 'Failed to load plugins' });
    } finally {
      setLoadingPlugins(false);
    }
  };

  const updateGenerationConfig = async (
    updates: Partial<GenerationConfig>,
    successText?: string
  ) => {
    try {
      const response = await api.setGenerationConfig(updates);
      setGenerationConfig(response.config);
      await notifyRuntimeChange();
      if (successText) {
        setMessage({ type: 'success', text: successText });
        setTimeout(() => setMessage(null), 4000);
      }
    } catch (error) {
      setMessage({
        type: 'error',
        text: `Failed to update generation settings: ${error instanceof Error ? error.message : 'Unknown error'}`,
      });
      setTimeout(() => setMessage(null), 5000);
    }
  };

  const handleOllamaModelSelect = async (modelName: string) => {
    try {
      await api.setOllamaModel(modelName);
      setMessage({ type: 'success', text: `Switched to ${modelName}` });
      await loadOllamaModels(); // Refresh to show updated current model
      await loadGenerationConfig();
      await notifyRuntimeChange();
    } catch (error) {
      setMessage({
        type: 'error',
        text: `Failed to set model: ${error instanceof Error ? error.message : 'Unknown error'}`
      });
    }

    setTimeout(() => setMessage(null), 5000);
  };

  const handleOllamaImageModelSelect = async (modelName: string) => {
    await updateGenerationConfig(
      { ollama_image_model: modelName },
      `Switched Ollama image model to ${modelName}`
    );
    await loadOllamaModels();
  };

  const handlePluginToggle = async (pluginName: string) => {
    try {
      const response = await api.togglePlugin(pluginName);
      await loadPlugins();
      await notifyRuntimeChange();
      setMessage({
        type: 'success',
        text: `${pluginName} ${response.enabled ? 'enabled' : 'disabled'}`,
      });
      setTimeout(() => setMessage(null), 4000);
    } catch (error) {
      setMessage({
        type: 'error',
        text: `Failed to toggle plugin: ${error instanceof Error ? error.message : 'Unknown error'}`
      });
      setTimeout(() => setMessage(null), 5000);
    }
  };

  const movePlugin = async (pluginName: string, direction: 'up' | 'down') => {
    const orderedPlugins = plugins.filter((plugin) => plugin.kind !== 'guard');
    const currentIndex = orderedPlugins.findIndex((plugin) => plugin.name === pluginName);
    if (currentIndex === -1) return;

    const targetIndex = direction === 'up' ? currentIndex - 1 : currentIndex + 1;
    if (targetIndex < 0 || targetIndex >= orderedPlugins.length) return;

    const nextPlugins = [...orderedPlugins];
    const [movedPlugin] = nextPlugins.splice(currentIndex, 1);
    nextPlugins.splice(targetIndex, 0, movedPlugin);

    setPlugins(nextPlugins.map((plugin, index) => ({ ...plugin, order: index + 1 })));

    try {
      await api.setPluginOrder(nextPlugins.map((plugin) => plugin.name));
      await loadPlugins();
      await notifyRuntimeChange();
    } catch (error) {
      await loadPlugins();
      setMessage({
        type: 'error',
        text: `Failed to reorder plugins: ${error instanceof Error ? error.message : 'Unknown error'}`
      });
      setTimeout(() => setMessage(null), 5000);
    }
  };

  const handleHFTokenSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hfToken.trim()) return;

    setIsSubmitting(true);
    try {
      await api.setHFToken(hfToken.trim());
      setMessage({ type: 'success', text: 'Hugging Face token saved to the local backend.' });

      setHFToken("");
      await loadHFTokenStatus();
    } catch (error) {
      setMessage({
        type: 'error',
        text: `Failed to save token: ${error instanceof Error ? error.message : 'Unknown error'}`
      });
    } finally {
      setIsSubmitting(false);
    }

    // Clear message after 5 seconds
    setTimeout(() => setMessage(null), 5000);
  };

  const handleModelDownload = async (modelId: string) => {
    try {
      setDownloadingModels(prev => new Set(prev).add(modelId));
      await api.downloadModel(modelId);
      setMessage({ type: 'success', text: `Started downloading ${modelId}` });
    } catch (error) {
      setDownloadingModels(prev => {
        const newSet = new Set(prev);
        newSet.delete(modelId);
        return newSet;
      });
      setMessage({
        type: 'error',
        text: `Failed to start download: ${error instanceof Error ? error.message : 'Unknown error'}`
      });
    }

    // Clear message after 5 seconds
    setTimeout(() => setMessage(null), 5000);
  };

  const handleUnloadModels = async () => {
    try {
      const result = await api.unloadModels();
      setMessage({ type: 'success', text: result.message });
      await loadModelStatus();
    } catch (error) {
      setMessage({ type: 'error', text: error instanceof Error ? error.message : 'Failed to unload models' });
    }
  };

  const toggleEnabledLora = async (loraName: string) => {
    const enabledLoras = generationConfig?.enabled_loras ?? [];
    const nextEnabledLoras = enabledLoras.includes(loraName)
      ? enabledLoras.filter((name) => name !== loraName)
      : [...enabledLoras, loraName];

    await updateGenerationConfig(
      { enabled_loras: nextEnabledLoras },
      nextEnabledLoras.includes(loraName)
        ? `Enabled LoRA ${loraName}`
        : `Disabled LoRA ${loraName}`
    );
  };

  const formatFileSize = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const getModelStatusColor = (status: ModelInfo['status']) => {
    switch (status) {
      case 'ready': return 'text-green-500';
      case 'downloading': return 'text-yellow-500';
      case 'partial': return 'text-orange-500';
      case 'not_downloaded': return 'text-gray-400';
      default: return 'text-gray-400';
    }
  };

  const getModelStatusIcon = (model: ModelInfo) => {
    const isDownloading = downloadingModels.has(model.id);

    if (isDownloading) {
      return <Loader2 className="w-4 h-4 text-yellow-500 animate-spin" />;
    }

    switch (model.status) {
      case 'ready': return <CheckCircle className="w-4 h-4 text-green-500" />;
      case 'downloading': return <Loader2 className="w-4 h-4 text-yellow-500 animate-spin" />;
      case 'partial': return <AlertCircle className="w-4 h-4 text-orange-500" />;
      case 'not_downloaded': return <Download className="w-4 h-4 text-gray-400" />;
      default: return <AlertCircle className="w-4 h-4 text-gray-400" />;
    }
  };

  const loraPluginEnabled = plugins.some((plugin) => plugin.name === "lora" && plugin.enabled);
  const enabledPromptPlugins = plugins.filter((plugin) => plugin.enabled && plugin.kind !== "guard");
  const enabledGuardPlugins = plugins.filter((plugin) => plugin.enabled && plugin.kind === "guard");
  const activeRuntimeModel = modelStatus?.models.find(
    (model) => model.backend === modelStatus.resolved_backend && model.status === "ready"
  );
  const entropyLevel = generationConfig?.entropy_level ?? "strange";
  const selectedBackend = generationConfig?.image_backend ?? "auto";
  const availableLoras = generationConfig?.available_loras ?? [];
  const enabledLoras = generationConfig?.enabled_loras ?? [];
  const loraProbability = generationConfig?.lora_application_probability ?? 0;
  const promptCapableModels = ollamaModels?.models.filter((model) => model.can_prompt) ?? [];
  const imageCapableModels = ollamaModels?.models.filter((model) => model.can_image) ?? [];
  const configuredPromptModel = ollamaModels?.configured_prompt ?? "";
  const activePromptModel = ollamaModels?.current ?? null;
  const configuredImageModel = generationConfig?.ollama_image_model ?? ollamaModels?.configured_image ?? "";
  const activeImageModel = ollamaModels?.current_image ?? null;
  const activeImageModelLabel =
    selectedBackend === "ollama"
      ? (activeImageModel ?? configuredImageModel) || "No Ollama image model"
      : generationConfig?.image_model ?? selectedBackend;
  const selectedBackendLabel =
    IMAGE_BACKEND_OPTIONS.find((backend) => backend.id === selectedBackend)?.label ?? selectedBackend;
  const promptModelFallback = generationConfig?.prompt_model ?? configuredPromptModel;

  const sections = [
    { id: "models", label: "Models", icon: Database },
    { id: "plugins", label: "Plugins", icon: SettingsIcon },
    { id: "ollama", label: "Prompt & Ollama", icon: Cpu },
    { id: "auth", label: "Authentication", icon: Key },
    { id: "system", label: "System", icon: Server },
  ];

  return (
    <div className="h-full flex flex-col lg:flex-row">
      {/* Settings Sidebar */}
      <div className="lg:w-64 border-b lg:border-b-0 lg:border-r border-border bg-card">
        <div className="p-4">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <SettingsIcon className="w-5 h-5 text-primary" />
            Settings
          </h2>
          <nav className="space-y-1">
            {sections.map((section) => {
              const Icon = section.icon;
              return (
                <button
                  key={section.id}
                  onClick={() => setActiveSection(section.id)}
                  className={cn(
                    "w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md transition-colors",
                    "hover:bg-background",
                    activeSection === section.id
                      ? "bg-background text-foreground font-medium"
                      : "text-muted-foreground"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  {section.label}
                </button>
              );
            })}
          </nav>
        </div>
      </div>

      {/* Settings Content */}
      <div className="flex-1 overflow-y-auto">
        <AnimatePresence mode="wait">
          {/* Models Section */}
          {activeSection === "models" && (
            <motion.div
              key="models"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="p-4 sm:p-6 lg:p-8"
            >
              <div className="max-w-4xl">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h3 className="text-xl font-semibold">Model Management</h3>
                    <p className="text-sm text-muted-foreground mt-1">
                      Pick the prompt model first, then the image model that renders it.
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      loadModelStatus();
                      loadGenerationConfig();
                      loadOllamaModels();
                    }}
                    className="p-2 hover:bg-background rounded-md transition-colors"
                    title="Refresh model status"
                  >
                    <RefreshCw className="w-4 h-4 text-muted-foreground" />
                  </button>
                </div>

                {modelStatus && (
                  <div className="mb-6 p-4 bg-muted/50 rounded-lg">
                    <div className="flex items-center gap-2 mb-2">
                      <HardDrive className="w-4 h-4 text-muted-foreground" />
                      <span className="text-sm font-medium">Cache Directory</span>
                    </div>
                    <code className="text-xs text-muted-foreground break-all">
                      {modelStatus.cache_dir}
                    </code>
                  </div>
                )}

                <div className="mb-6 space-y-6">
                  <div className="border border-primary/30 bg-primary/5 rounded-lg p-4">
                    <div className="mb-4 flex items-start justify-between gap-3">
                      <div>
                        <h4 className="font-medium">Two-stage generation pipeline</h4>
                        <p className="text-sm text-muted-foreground mt-1">
                          DreamGen first asks Ollama for a final prompt, then sends that prompt to the selected image renderer.
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setActiveSection("ollama")}
                        className="shrink-0 rounded-md border border-border bg-background px-3 py-1.5 text-xs transition-colors hover:border-primary/50"
                      >
                        All Ollama models
                      </button>
                    </div>

                    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:items-stretch">
                      <div className="rounded-lg border border-border bg-background/85 p-4">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <Brain className="h-4 w-4 text-primary" />
                            <span className="text-sm font-medium">Stage 1: Prompt model</span>
                          </div>
                          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                            Ollama
                          </span>
                        </div>
                        <div className="mt-3 text-sm font-medium text-foreground break-all">
                          {activePromptModel ?? promptModelFallback ?? "No prompt model"}
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {loadingOllama ? (
                            <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                              <Loader2 className="h-3 w-3 animate-spin" />
                              Loading prompt models
                            </span>
                          ) : promptCapableModels.length > 0 ? (
                            promptCapableModels.slice(0, 4).map((model) => {
                              const isCurrent = model.name === activePromptModel;
                              return (
                                <button
                                  key={`pipeline-prompt-${model.name}`}
                                  type="button"
                                  onClick={() => handleOllamaModelSelect(model.name)}
                                  className={cn(
                                    "rounded-full border px-3 py-1.5 text-xs transition-colors",
                                    isCurrent
                                      ? "border-primary bg-primary text-primary-foreground"
                                      : "border-border hover:bg-muted/40"
                                  )}
                                >
                                  {model.name}
                                </button>
                              );
                            })
                          ) : (
                            <span className="text-xs text-muted-foreground">
                              No completion-capable Ollama models found.
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="hidden items-center justify-center text-muted-foreground lg:flex">
                        <ArrowRight className="h-5 w-5" />
                      </div>

                      <div className="rounded-lg border border-border bg-background/85 p-4">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <ImageIcon className="h-4 w-4 text-primary" />
                            <span className="text-sm font-medium">Stage 2: Image model</span>
                          </div>
                          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                            {selectedBackendLabel}
                          </span>
                        </div>
                        <div className="mt-3 text-sm font-medium text-foreground break-all">
                          {activeImageModelLabel}
                        </div>
                        {selectedBackend === "ollama" && configuredImageModel && activeImageModel && configuredImageModel !== activeImageModel && (
                          <div className="mt-2 text-xs text-amber-700 dark:text-amber-300">
                            Configured {configuredImageModel}; using {activeImageModel}.
                          </div>
                        )}
                        <div className="mt-3 text-xs text-muted-foreground">
                          Use the backend choices below for local Diffusers, Qwen, Z-Image, or Ollama image rendering.
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="border border-border rounded-lg p-4">
                    {modelStatus && (
                      <div className="mb-4 grid gap-3 rounded-lg border border-primary/25 bg-primary/5 p-4 sm:grid-cols-3">
                        <div>
                          <div className="text-xs uppercase tracking-wide text-muted-foreground">Runtime</div>
                          <div className="mt-1 font-medium capitalize">{modelStatus.configured_backend} → {modelStatus.resolved_backend}</div>
                        </div>
                        <div>
                          <div className="text-xs uppercase tracking-wide text-muted-foreground">Memory</div>
                          <div className="mt-1 font-medium">
                            {modelStatus.memory.cuda.available
                              ? `${modelStatus.memory.cuda.free_gb} / ${modelStatus.memory.cuda.total_gb} GB VRAM free`
                              : `${modelStatus.memory.system.available_gb} / ${modelStatus.memory.system.total_gb} GB RAM free`}
                          </div>
                        </div>
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <div className="text-xs uppercase tracking-wide text-muted-foreground">Recommended</div>
                            <div className="mt-1 font-medium capitalize">{modelStatus.recommended.backend} · {modelStatus.recommended.width}²</div>
                          </div>
                          <button type="button" onClick={() => void handleUnloadModels()} className="rounded-md border border-border px-3 py-2 text-xs hover:bg-muted">
                            Unload
                          </button>
                        </div>
                      </div>
                    )}
                    <div className="flex items-center gap-2 mb-3">
                      <SlidersHorizontal className="w-4 h-4 text-primary" />
                      <div>
                        <h4 className="font-medium">Image backend selector</h4>
                        <p className="text-sm text-muted-foreground">
                          Choose which renderer DreamGen uses in stage 2.
                        </p>
                      </div>
                    </div>

                    {loadingGenerationConfig ? (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Loading generation settings...
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                        {IMAGE_BACKEND_OPTIONS.map((backend) => {
                          const isActive = selectedBackend === backend.id;
                          return (
                            <button
                              key={backend.id}
                              type="button"
                              onClick={() =>
                                updateGenerationConfig(
                                  { image_backend: backend.id },
                                  `Switched image backend to ${backend.label}`
                                )
                              }
                              className={cn(
                                "rounded-lg border p-3 text-left transition-colors",
                                isActive
                                  ? "border-primary bg-primary/5"
                                  : "border-border hover:bg-muted/40"
                              )}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-medium">{backend.label}</span>
                                {isActive && (
                                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-primary/15 text-primary">
                                    Active
                                  </span>
                                )}
                              </div>
                              <p className="mt-2 text-xs text-muted-foreground">
                                {backend.description}
                              </p>
                            </button>
                          );
                        })}
                      </div>
                    )}

                    {selectedBackend === "ollama" && (
                      <div className="mt-4 rounded-md bg-muted/50 p-3 text-sm text-muted-foreground">
                        DreamGen will call Ollama&apos;s experimental image API with the selected Ollama image model.
                        {activeImageModel ? (
                          <span className="block mt-1 text-foreground">
                            Active image model: {activeImageModel}
                          </span>
                        ) : (
                          <span className="block mt-1 text-amber-600 dark:text-amber-300">
                            No image-capable Ollama model is currently available.
                          </span>
                        )}
                      </div>
                    )}

                    {selectedBackend === "ernie" && (
                      <div className="mt-4 grid gap-3 rounded-md bg-muted/50 p-3 text-sm">
                        <div className="text-muted-foreground">
                          ERNIE-Image-Turbo runs locally through Diffusers with an optional prompt enhancer before rendering.
                        </div>
                        <label className="grid gap-1">
                          <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                            ERNIE model
                          </span>
                          <input
                            value={generationConfig?.ernie_image_model ?? "baidu/ERNIE-Image-Turbo"}
                            onChange={(event) =>
                              updateGenerationConfig({ ernie_image_model: event.target.value })
                            }
                            className="rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                          />
                        </label>
                        <label className="flex items-center justify-between gap-3 rounded-md border border-border bg-background/75 px-3 py-2">
                          <span>
                            <span className="block text-sm font-medium text-foreground">
                              Prompt enhancer
                            </span>
                            <span className="text-xs text-muted-foreground">
                              Improves visual quality, but may soften strict instruction following.
                            </span>
                          </span>
                          <input
                            type="checkbox"
                            checked={generationConfig?.ernie_prompt_enhancer !== false}
                            onChange={(event) =>
                              updateGenerationConfig({ ernie_prompt_enhancer: event.target.checked })
                            }
                            className="h-4 w-4 accent-primary"
                          />
                        </label>
                      </div>
                    )}
                  </div>

                  <div className="border border-border rounded-lg p-4">
                    <div className="flex items-start justify-between gap-3 mb-4">
                      <div className="flex items-start gap-2">
                        <Sparkles className="w-4 h-4 text-primary mt-0.5" />
                        <div>
                          <h4 className="font-medium">Local LoRA Library</h4>
                          <p className="text-sm text-muted-foreground">
                            Select which local LoRAs are eligible when the <code className="text-xs">lora</code> plugin runs.
                          </p>
                        </div>
                      </div>
                      <span className="text-xs px-2 py-1 rounded-full bg-muted text-muted-foreground">
                        {availableLoras.length} detected
                      </span>
                    </div>

                    <div className="space-y-4">
                      <div className="rounded-md bg-muted/50 p-3">
                        <div className="text-xs font-medium text-foreground mb-1">LoRA Directory</div>
                        <code className="text-xs text-muted-foreground break-all">
                          {generationConfig?.lora_dir ?? "./loras"}
                        </code>
                      </div>

                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-sm font-medium">Application probability</label>
                          <span className="text-xs text-muted-foreground">
                            {Math.round(loraProbability * 100)}%
                          </span>
                        </div>
                        <input
                          type="range"
                          min="0"
                          max="1"
                          step="0.05"
                          value={loraProbability}
                          onChange={(e) =>
                            updateGenerationConfig({
                              lora_application_probability: parseFloat(e.target.value),
                            })
                          }
                          className="w-full"
                        />
                        <p className="text-xs text-muted-foreground mt-1">
                          Higher values make LoRA selection more likely when the plugin is enabled.
                        </p>
                      </div>

                      {!loraPluginEnabled && (
                        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                          The <code>lora</code> plugin is currently disabled. Enable it in the Plugins tab if you want these adapters to be applied.
                        </div>
                      )}

                      {selectedBackend === "zimage" && !generationConfig?.zimage_native_available && enabledLoras.length === 0 && (
                        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                          Z-Image without an active LoRA still expects a local <code>ref-repos/Z-Image</code> checkout. If you want the simplified DiffSynth path, keep at least one LoRA enabled.
                        </div>
                      )}

                      {availableLoras.length > 0 ? (
                        <div className="flex flex-wrap gap-2">
                          {availableLoras.map((loraName) => {
                            const isEnabled = enabledLoras.includes(loraName);
                            return (
                              <button
                                key={loraName}
                                type="button"
                                onClick={() => toggleEnabledLora(loraName)}
                                className={cn(
                                  "rounded-full border px-3 py-1.5 text-sm transition-colors",
                                  isEnabled
                                    ? "border-primary bg-primary text-primary-foreground"
                                    : "border-border hover:bg-muted/40"
                                )}
                              >
                                {loraName}
                              </button>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
                          No LoRAs found yet. Add adapters under <code>{generationConfig?.lora_dir ?? "./loras"}</code> and refresh this page.
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div>
                    <h4 className="font-medium">Image model downloads</h4>
                    <p className="text-sm text-muted-foreground mt-1">
                      Hugging Face and local checkpoints used by the stage 2 renderers.
                    </p>
                  </div>
                  {modelStatus?.models.map((model) => {
                    const isDownloading = downloadingModels.has(model.id);
                    const canDownload =
                      model.downloadable !== false &&
                      (model.status === 'not_downloaded' || model.status === 'partial');

                    return (
                      <div
                        key={model.id}
                        className="border border-border rounded-lg p-4 hover:bg-muted/30 transition-colors"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            {getModelStatusIcon(model)}
                            <div>
                              <h4 className="font-medium">{model.name}</h4>
                              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                                <span className="capitalize">{model.type.replace('-', ' ')}</span>
                                <span>•</span>
                                <span className={getModelStatusColor(model.status)}>
                                  {model.status.replace('_', ' ').toUpperCase()}
                                </span>
                                {model.size > 0 && (
                                  <>
                                    <span>•</span>
                                    <span>{formatFileSize(model.size)}</span>
                                  </>
                                )}
                              </div>
                              {model.incomplete_files > 0 && (
                                <div className="text-xs text-orange-500 mt-1">
                                  {model.incomplete_files} files downloading...
                                </div>
                              )}
                              {model.path && model.id === "local:zimage" && (
                                <div className="text-xs text-muted-foreground mt-1 break-all">
                                  {model.path}
                                </div>
                              )}
                            </div>
                          </div>

                          <div className="flex items-center gap-2">
                            {canDownload && !isDownloading && (
                              <button
                                onClick={() => handleModelDownload(model.id)}
                                className="px-3 py-1.5 bg-primary text-primary-foreground text-xs rounded-md hover:opacity-90 transition-opacity"
                              >
                                {model.id === "local:zimage" ? "Download Local Copy" : "Download"}
                              </button>
                            )}
                            {isDownloading && (
                              <div className="flex items-center gap-2 text-xs text-yellow-600">
                                <Loader2 className="w-3 h-3 animate-spin" />
                                Downloading...
                              </div>
                            )}
                            {model.status === 'ready' && (
                              <div className="flex items-center gap-2 text-xs text-green-600">
                                <CheckCircle className="w-3 h-3" />
                                Ready
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </motion.div>
          )}

          {/* Ollama Section */}
          {activeSection === "ollama" && (
            <motion.div
              key="ollama"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="p-4 sm:p-6 lg:p-8"
            >
              <div className="max-w-4xl">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h3 className="text-xl font-semibold">Prompt and Ollama Image Models</h3>
                    <p className="text-sm text-muted-foreground mt-1">
                      Pick the Ollama model for prompt generation separately from Ollama image rendering.
                    </p>
                  </div>
                  <button
                    onClick={loadOllamaModels}
                    className="p-2 hover:bg-background rounded-md transition-colors"
                    title="Refresh Ollama models"
                    disabled={loadingOllama}
                  >
                    <RefreshCw className={cn("w-4 h-4 text-muted-foreground", loadingOllama && "animate-spin")} />
                  </button>
                </div>

                {ollamaModels && (
                  <div className="mb-6 p-4 bg-muted/50 rounded-lg">
                    <div className="flex flex-wrap items-center gap-4 text-sm">
                      <div className="flex items-center gap-2">
                        <Server className="w-4 h-4 text-muted-foreground" />
                        <span className="font-medium">Ollama Host</span>
                        <code className="text-xs text-muted-foreground">
                          {ollamaModels.host}
                        </code>
                      </div>
                      <div className="flex items-center gap-2">
                        <Cpu className="w-4 h-4 text-muted-foreground" />
                        <span className="font-medium">Version</span>
                        <code className="text-xs text-muted-foreground">
                          {ollamaModels.version || "unknown"}
                        </code>
                      </div>
                    </div>
                  </div>
                )}

                {loadingOllama ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="w-8 h-8 animate-spin text-primary" />
                  </div>
                ) : ollamaModels && ollamaModels.models.length > 0 ? (
                  <div className="space-y-6">
                    <div>
                      <div className="mb-3">
                        <h4 className="font-medium">Prompt Models</h4>
                        <p className="text-sm text-muted-foreground mt-1">
                          Completion-capable models used for the Generate Prompt action.
                        </p>
                      </div>

                      {promptCapableModels.length > 0 ? (
                        <div className="space-y-2">
                          {promptCapableModels.map((model) => {
                            const isCurrent = model.name === activePromptModel;
                            const sizeInGB = (model.size / (1024 * 1024 * 1024)).toFixed(2);

                            return (
                              <button
                                key={`prompt-${model.name}`}
                                onClick={() => handleOllamaModelSelect(model.name)}
                                className={cn(
                                  "w-full border rounded-lg p-4 transition-all text-left",
                                  "hover:bg-muted/50 hover:border-primary/50",
                                  isCurrent ? "border-primary bg-primary/5" : "border-border"
                                )}
                              >
                                <div className="flex items-start justify-between gap-3">
                                  <div className="flex-1">
                                    <div className="flex items-center gap-2 flex-wrap">
                                      <h5 className="font-medium">{model.name}</h5>
                                      {isCurrent && (
                                        <span className="text-xs px-2 py-0.5 bg-primary/20 text-primary rounded-full">
                                          Active Prompt
                                        </span>
                                      )}
                                      {model.can_vision && (
                                        <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                                          Vision
                                        </span>
                                      )}
                                    </div>
                                    <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1 flex-wrap">
                                      <span>{sizeInGB} GB</span>
                                      {model.format && (
                                        <>
                                          <span>•</span>
                                          <span>{model.format}</span>
                                        </>
                                      )}
                                      <span>•</span>
                                      <span>{new Date(model.modified).toLocaleDateString()}</span>
                                    </div>
                                  </div>
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
                          No completion-capable Ollama models found. Install a chat/completion model to use prompt generation.
                        </div>
                      )}
                    </div>

                    <div>
                      <div className="mb-3">
                        <h4 className="font-medium">Image Models</h4>
                        <p className="text-sm text-muted-foreground mt-1">
                          Image-capable Ollama models used when the backend is set to <code>Ollama Image</code>.
                        </p>
                      </div>

                      {configuredImageModel && activeImageModel && configuredImageModel !== activeImageModel && (
                        <div className="mb-3 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                          Configured Ollama image model <code>{configuredImageModel}</code> is not usable on this host. DreamGen is falling back to <code>{activeImageModel}</code>.
                        </div>
                      )}

                      {imageCapableModels.length > 0 ? (
                        <div className="space-y-2">
                          {imageCapableModels.map((model) => {
                            const isCurrent = model.name === activeImageModel;
                            const sizeInGB = (model.size / (1024 * 1024 * 1024)).toFixed(2);

                            return (
                              <button
                                key={`image-${model.name}`}
                                onClick={() => handleOllamaImageModelSelect(model.name)}
                                className={cn(
                                  "w-full border rounded-lg p-4 transition-all text-left",
                                  "hover:bg-muted/50 hover:border-primary/50",
                                  isCurrent ? "border-primary bg-primary/5" : "border-border"
                                )}
                              >
                                <div className="flex items-start justify-between gap-3">
                                  <div className="flex-1">
                                    <div className="flex items-center gap-2 flex-wrap">
                                      <h5 className="font-medium">{model.name}</h5>
                                      {isCurrent && (
                                        <span className="text-xs px-2 py-0.5 bg-primary/20 text-primary rounded-full">
                                          Active Image
                                        </span>
                                      )}
                                      <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                                        {model.family || model.format || "image"}
                                      </span>
                                    </div>
                                    <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1 flex-wrap">
                                      <span>{sizeInGB} GB</span>
                                      {model.format && (
                                        <>
                                          <span>•</span>
                                          <span>{model.format}</span>
                                        </>
                                      )}
                                      <span>•</span>
                                      <span>{new Date(model.modified).toLocaleDateString()}</span>
                                    </div>
                                  </div>
                                </div>
                              </button>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
                          No image-capable Ollama models found. Install one like <code>x/z-image-turbo</code> or <code>x/flux2-klein</code> to use the Ollama image backend.
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-12">
                    <AlertCircle className="w-12 h-12 text-muted-foreground/30 mx-auto mb-4" />
                    <p className="text-sm text-muted-foreground">No Ollama models found</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Make sure Ollama is running and has models installed
                    </p>
                  </div>
                )}
              </div>
            </motion.div>
          )}

          {/* Plugins Section */}
          {activeSection === "plugins" && (
            <motion.div
              key="plugins"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="p-4 sm:p-6 lg:p-8"
            >
              <div className="max-w-4xl">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h3 className="text-xl font-semibold">Plugin Controls</h3>
                    <p className="text-sm text-muted-foreground mt-1">
                      Enable plugins and adjust execution order
                    </p>
                  </div>
                  <button
                    onClick={loadPlugins}
                    className="p-2 hover:bg-background rounded-md transition-colors"
                    title="Refresh plugins"
                    disabled={loadingPlugins}
                  >
                    <RefreshCw className={cn("w-4 h-4 text-muted-foreground", loadingPlugins && "animate-spin")} />
                  </button>
                </div>

                {loadingPlugins ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="w-8 h-8 animate-spin text-primary" />
                  </div>
                ) : (
                  <div className="space-y-3">
                    {plugins.map((plugin, index) => (
                      <div
                        key={plugin.name}
                        className="border border-border rounded-lg p-4 flex items-start gap-4"
                      >
                        <button
                          type="button"
                          onClick={() => handlePluginToggle(plugin.name)}
                          className={cn(
                            "mt-0.5 h-5 w-9 rounded-full transition-colors relative shrink-0",
                            plugin.enabled ? "bg-primary" : "bg-muted"
                          )}
                          aria-label={`Toggle ${plugin.name}`}
                        >
                          <span
                            className={cn(
                              "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform",
                              plugin.enabled ? "translate-x-4" : "translate-x-0.5"
                            )}
                          />
                        </button>

                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <h4 className="font-medium">{plugin.name}</h4>
                            <span className="text-xs px-2 py-0.5 bg-muted text-muted-foreground rounded-full">
                              {plugin.category ?? "context"}
                            </span>
                            {plugin.kind === "guard" && (
                              <span className="text-xs px-2 py-0.5 bg-amber-500/10 text-amber-600 rounded-full">
                                hook
                              </span>
                            )}
                            <span className="text-xs px-2 py-0.5 bg-muted text-muted-foreground rounded-full">
                              #{plugin.order}
                            </span>
                          </div>
                          <p className="text-sm text-muted-foreground mt-1">
                            {plugin.description}
                          </p>
                        </div>

                        <div className="flex flex-col gap-2 shrink-0">
                          {plugin.name === "dream_source_mixer" && (
                            <select
                              value={entropyLevel}
                              onChange={(event) =>
                                updateGenerationConfig({
                                  entropy_level: event.target.value as "calm" | "strange" | "wild",
                                })
                              }
                              className="rounded border border-border bg-background px-2 py-1 text-xs"
                              aria-label="Dream Source Mixer entropy level"
                            >
                              <option value="calm">calm</option>
                              <option value="strange">strange</option>
                              <option value="wild">wild</option>
                            </select>
                          )}
                          {plugin.kind !== "guard" && <>
                          <button
                            type="button"
                            onClick={() => movePlugin(plugin.name, 'up')}
                            disabled={index === 0}
                            className="p-2 border border-border rounded-md hover:bg-muted/50 disabled:opacity-40 disabled:cursor-not-allowed"
                            aria-label={`Move ${plugin.name} up`}
                          >
                            <ArrowUp className="w-4 h-4" />
                          </button>
                          <button
                            type="button"
                            onClick={() => movePlugin(plugin.name, 'down')}
                            disabled={index === plugins.length - 1}
                            className="p-2 border border-border rounded-md hover:bg-muted/50 disabled:opacity-40 disabled:cursor-not-allowed"
                            aria-label={`Move ${plugin.name} down`}
                          >
                            <ArrowDown className="w-4 h-4" />
                          </button>
                          </>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          )}

          {/* Authentication Section */}
          {activeSection === "auth" && (
            <motion.div
              key="auth"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="p-4 sm:p-6 lg:p-8"
            >
              <div className="max-w-2xl">
                <h3 className="text-xl font-semibold mb-6">Authentication</h3>

                {/* HF Token Section */}
                <div className="space-y-6">
                  <div className="border border-border rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-4">
                      <Key className="w-5 h-5 text-primary" />
                      <h4 className="text-lg font-medium">HuggingFace Token</h4>
                      {hfTokenStatus?.configured && (
                        <div className="flex items-center gap-1 text-xs text-green-600">
                          <CheckCircle className="w-3 h-3" />
                          Configured ({hfTokenStatus.source})
                        </div>
                      )}
                    </div>

                    <p className="text-sm text-muted-foreground mb-4">
                      Optional for public fallback models. Useful for gated or private model downloads
                      and for avoiding rate limits. The token is sent to this local backend, stored in
                      its configured Hugging Face cache, and is never persisted in the browser.
                      Get your token from{" "}
                      <a
                        href="https://huggingface.co/settings/tokens"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline"
                      >
                        HuggingFace Settings
                      </a>
                    </p>

                    <form onSubmit={handleHFTokenSubmit} className="space-y-4">
                      <div className="relative">
                        <input
                          type={showToken ? "text" : "password"}
                          value={hfToken}
                          onChange={(e) => setHFToken(e.target.value)}
                          placeholder="hf_..."
                          className="w-full px-3 py-2 pr-10 bg-background border border-input rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary/50"
                        />
                        <button
                          type="button"
                          onClick={() => setShowToken(!showToken)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          aria-label={showToken ? "Hide Hugging Face token" : "Show Hugging Face token"}
                          title={showToken ? "Hide token" : "Show token"}
                        >
                          {showToken ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                        </button>
                      </div>

                      <button
                        type="submit"
                        disabled={!hfToken.trim() || isSubmitting}
                        className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 transition-opacity text-sm font-medium"
                      >
                        {isSubmitting ? (
                          <div className="flex items-center gap-2">
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Saving...
                          </div>
                        ) : (
                          "Save Token"
                        )}
                      </button>
                    </form>
                  </div>

                  <div className="border border-border rounded-lg p-4 bg-muted/20">
                    <div className="flex items-center gap-2 mb-3">
                      <AlertCircle className="w-5 h-5 text-primary" />
                      <h4 className="text-lg font-medium">Cloudflare deployment</h4>
                      <span className="text-xs rounded-full bg-muted px-2 py-0.5 text-muted-foreground">
                        Explicit setup only
                      </span>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      DreamGen does not implement Cloudflare OAuth, account linking, or automatic
                      Worker provisioning from this page. Nothing is deployed or authorized here.
                      Deploy your own Workers or Pages project explicitly with Wrangler or the
                      repository workflow after reviewing the requested account and R2 scopes.
                    </p>
                    <p className="text-xs text-muted-foreground mt-3">
                      Keep Cloudflare credentials in your deployment environment; do not enter them
                      into DreamGen or commit them to the repository. This local API is an operator
                      surface, not a customer-account login gateway.
                    </p>
                  </div>
                </div>
              </div>
            </motion.div>
          )}

          {/* System Section */}
          {activeSection === "system" && (
            <motion.div
              key="system"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="p-4 sm:p-6 lg:p-8"
            >
              <div className="max-w-3xl">
                <h3 className="text-xl font-semibold">System Information</h3>
                <p className="text-sm text-muted-foreground mt-1 mb-6">
                  Live readiness, runtime, resource, and plugin guard state from the backend.
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div className="border border-border rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Server className="w-4 h-4 text-muted-foreground" />
                      <span className="text-sm font-medium">Backend readiness</span>
                    </div>
                    <div className={cn(
                      "text-lg font-semibold",
                      systemStatus?.status === "ready" ? "text-green-500" : "text-orange-500"
                    )}>
                      {systemStatus ? (systemStatus.status === "ready" ? "Ready" : systemStatus.status) : "Unavailable"}
                    </div>
                    <p className="text-xs text-muted-foreground mt-2">
                      {systemStatus
                        ? `Image backend: ${systemStatus.backend}. Prompt service: ${systemStatus.ollama_available ? "online" : "unavailable"}.`
                        : "The /api/status response has not loaded."}
                    </p>
                  </div>

                  <div className="border border-border rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Database className="w-4 h-4 text-muted-foreground" />
                      <span className="text-sm font-medium">Active runtime</span>
                    </div>
                    <div className="text-lg font-semibold text-foreground capitalize">
                      {modelStatus?.resolved_backend ?? (modelStatusError ? "Unavailable" : "Loading…")}
                    </div>
                    <p className="text-xs text-muted-foreground mt-2">
                      {modelStatus
                        ? `${modelStatus.configured_backend} configured → ${activeRuntimeModel?.name ?? "runtime model not identified"}.`
                        : modelStatusError
                          ? "The /api/models/status response is unavailable."
                          : "Loading /api/models/status…"}
                    </p>
                  </div>

                  <div className="border border-border rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Cpu className="w-4 h-4 text-muted-foreground" />
                      <span className="text-sm font-medium">Device & resources</span>
                    </div>
                    <div className={cn(
                      "text-lg font-semibold",
                      modelStatus?.memory.cuda.available || systemStatus?.gpu_available
                        ? "text-green-500"
                        : "text-orange-500"
                    )}>
                      {modelStatus
                        ? (modelStatus.memory.cuda.available
                          ? modelStatus.memory.cuda.device ?? "CUDA available"
                          : "CPU only")
                        : systemStatus
                          ? (systemStatus.gpu_available ? "GPU available" : "CPU only")
                          : "Unavailable"}
                    </div>
                    <p className="text-xs text-muted-foreground mt-2">
                      {modelStatus
                        ? (modelStatus.memory.cuda.available && modelStatus.memory.cuda.free_gb !== undefined
                          ? `${modelStatus.memory.cuda.free_gb.toFixed(1)} / ${modelStatus.memory.cuda.total_gb?.toFixed(1) ?? "?"} GB VRAM free.`
                          : `${modelStatus.memory.system.available_gb.toFixed(1)} / ${modelStatus.memory.system.total_gb.toFixed(1)} GB RAM free.`)
                        : "Resource details are unavailable until the model status loads."}
                    </p>
                  </div>

                  <div className="border border-border rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <SettingsIcon className="w-4 h-4 text-muted-foreground" />
                      <span className="text-sm font-medium">Plugins & guards</span>
                    </div>
                    <div className="text-lg font-semibold text-foreground">
                      {pluginsError
                        ? "Unavailable"
                        : loadingPlugins
                          ? "Loading…"
                          : `${enabledPromptPlugins.length} prompt · ${enabledGuardPlugins.length} guard`}
                    </div>
                    <p className="text-xs text-muted-foreground mt-2">
                      {pluginsError
                        ? "The /api/plugins response is unavailable."
                        : loadingPlugins
                          ? "Loading plugin state…"
                          : `Prompt: ${enabledPromptPlugins.map((plugin) => plugin.name.replaceAll("_", " ")).join(", ") || "none"}. Guard: ${enabledGuardPlugins.map((plugin) => plugin.name.replaceAll("_", " ")).join(", ") || "none"}.`}
                    </p>
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Status Message */}
      <AnimatePresence>
        {message && (
          <motion.div
            initial={{ opacity: 0, y: 50 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 50 }}
            className="fixed bottom-4 right-4 z-50"
          >
            <div className={cn(
              "px-4 py-3 rounded-lg shadow-lg text-sm font-medium",
              message.type === 'success'
                ? "bg-green-500 text-white"
                : "bg-red-500 text-white"
            )}>
              {message.text}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
