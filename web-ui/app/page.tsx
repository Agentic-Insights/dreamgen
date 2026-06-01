"use client";

import { startTransition, useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import {
  Check,
  Clock3,
  Image as ImageIcon,
  Loader2,
  Play,
  RotateCcw,
  Settings as SettingsIcon,
  ChevronDown,
  ChevronRight,
  SlidersHorizontal,
  Sparkles,
  Square,
  Wand2,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import Gallery from "@/components/Gallery";
import Settings from "@/components/Settings";
import AdvancedControls from "@/components/AdvancedControls";
import MetaPromptModal from "@/components/MetaPromptModal";
import TaskProgress from "@/components/TaskProgress";
import {
  API_BASE,
  api,
  GenerationEvent,
  GenerateResponse,
  GenerationConfig,
  PluginInfo,
  SystemStatus,
} from "@/lib/api";
import {
  createClientRequestId,
  getFallbackProgress,
  getTaskProgressUpdate,
  INITIAL_IMAGE_PROGRESS,
  INITIAL_PROMPT_PROGRESS,
  type ProgressSnapshot,
} from "@/lib/task-progress";
import { cn } from "@/lib/utils";
import galleryCache from "@/lib/cache";

type TabId = "generate" | "gallery" | "settings";

type CadenceOption = {
  label: string;
  minutes: number;
  description: string;
};

type RecentImage = {
  path: string;
  prompt: string;
  created_at: string;
};

const CADENCE_OPTIONS: CadenceOption[] = [
  { label: "5 min", minutes: 5, description: "Fast drip" },
  { label: "15 min", minutes: 15, description: "Steady stream" },
  { label: "1 hour", minutes: 60, description: "Background rhythm" },
  { label: "3 hours", minutes: 180, description: "Slow drift" },
  { label: "Daily", minutes: 1440, description: "One image a day" },
];

const DASHBOARD_BACKEND_OPTIONS = [
  { id: "auto", label: "Auto" },
  { id: "zimage", label: "Z-Image" },
  { id: "qwen", label: "Qwen" },
  { id: "ernie", label: "ERNIE" },
  { id: "ollama", label: "Ollama" },
  { id: "small", label: "Small SD" },
  { id: "turbo", label: "Turbo" },
  { id: "mock", label: "Mock" },
] as const;

const STORAGE_KEYS = {
  promptSeed: "dreamgen.promptSeed",
  cadenceMinutes: "dreamgen.cadenceMinutes",
  sessionLoop: "dreamgen.sessionLoop",
};

const readString = (key: string, fallback: string) => {
  if (typeof window === "undefined") return fallback;
  return window.localStorage.getItem(key) ?? fallback;
};

const readNumber = (key: string, fallback: number) => {
  if (typeof window === "undefined") return fallback;
  const raw = window.localStorage.getItem(key);
  const value = raw ? Number(raw) : NaN;
  return Number.isFinite(value) ? value : fallback;
};

const readBoolean = (key: string, fallback: boolean) => {
  if (typeof window === "undefined") return fallback;
  const raw = window.localStorage.getItem(key);
  if (raw === null) return fallback;
  return raw === "true";
};

const formatCountdown = (target: Date | null) => {
  if (!target) return "Not scheduled";

  const diffMs = target.getTime() - Date.now();
  if (diffMs <= 0) return "Running now";

  const totalSeconds = Math.ceil(diffMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
};

const truncatePrompt = (prompt: string, max = 88) =>
  prompt.length > max ? `${prompt.slice(0, max).trim()}...` : prompt;

const describeGenerationEvent = (event: GenerationEvent) => {
  if (event.type === "generation_error") return `Error: ${event.error ?? "unknown"}`;
  if (event.type === "generation_started") return "Generation started";
  if (event.type === "generation_completed") return "Generation completed";
  if (event.label) return event.label;
  if (event.name) return event.name.replaceAll("_", " ");
  return event.type.replaceAll("_", " ");
};

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabId>("generate");
  const [promptSeed, setPromptSeed] = useState("");
  const [metaPrompt, setMetaPrompt] = useState("");
  const [promptError, setPromptError] = useState<string | null>(null);
  const [isGeneratingPrompt, setIsGeneratingPrompt] = useState(false);
  const [promptProgress, setPromptProgress] = useState<ProgressSnapshot | null>(null);
  const [showMetaPromptModal, setShowMetaPromptModal] = useState(false);
  const [promptBuilderOpen, setPromptBuilderOpen] = useState(true);
  const [runControlsOpen, setRunControlsOpen] = useState(false);
  const [seed, setSeed] = useState<number | null>(null);
  const [cadenceMinutes, setCadenceMinutes] = useState(60);
  const [loopEnabled, setLoopEnabled] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationProgress, setGenerationProgress] = useState<ProgressSnapshot | null>(null);
  const [currentImage, setCurrentImage] = useState<GenerateResponse | null>(null);
  const [recentImages, setRecentImages] = useState<RecentImage[]>([]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [generationConfig, setGenerationConfig] = useState<GenerationConfig | null>(null);
  const [generationEvents, setGenerationEvents] = useState<GenerationEvent[]>([]);
  const [nextRunAt, setNextRunAt] = useState<Date | null>(null);
  const [, setClockTick] = useState(Date.now());
  const [sessionCount, setSessionCount] = useState(0);
  const [logs, setLogs] = useState<string[]>(["DreamGen is ready."]);

  const promptSeedRef = useRef(promptSeed);
  const cadenceMinutesRef = useRef(cadenceMinutes);
  const isGeneratingRef = useRef(isGenerating);
  const statusRef = useRef<SystemStatus | null>(status);
  const runGenerationRef = useRef<(source: "manual" | "loop") => Promise<void>>(
    async () => {}
  );
  const promptRequestIdRef = useRef<string | null>(null);
  const generationRequestIdRef = useRef<string | null>(null);
  const promptResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generationResetTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const currentBackend =
    currentImage?.metadata.backend && currentImage.metadata.backend !== "unknown"
      ? currentImage.metadata.backend
      : status?.backend ?? "unknown";
  const currentPluginCount =
    currentImage?.metadata.plugins_used?.length && currentImage.metadata.plugins_used.length > 0
      ? currentImage.metadata.plugins_used.length
      : status?.active_plugins?.length ?? 0;
  const isSmokeBackend = currentBackend === "smoke-test";
  const enabledPlugins = plugins.filter((plugin) => plugin.enabled);
  const selectedBackend = generationConfig?.image_backend ?? "auto";
  const enabledLoras = generationConfig?.enabled_loras ?? [];
  const promptModelLabel = generationConfig?.prompt_model ?? generationConfig?.ollama_model ?? "Ollama prompt model";
  const imageModelLabel =
    selectedBackend === "ollama"
      ? generationConfig?.ollama_image_model || "Ollama image model"
      : generationConfig?.image_model ?? selectedBackend;
  const lastActivity = logs[logs.length - 1];

  const addLog = (message: string, type: "info" | "error" = "info") => {
    const timestamp = new Date().toLocaleTimeString();
    const prefix = type === "error" ? "[ERROR]" : "[INFO]";
    startTransition(() => {
      setLogs((prev) => [...prev.slice(-11), `${timestamp} ${prefix} ${message}`]);
    });
  };

  const loadRecentImages = useCallback(async () => {
    try {
      const response = await api.getGallery(6, 0);
      const latestImage = response.images[0];
      const latestStatus = statusRef.current;
      startTransition(() => {
        setRecentImages(response.images);
        if (latestImage) {
          setCurrentImage((existing) =>
            existing ??
            ({
              id: latestImage.path,
              prompt: latestImage.prompt,
              image_path: latestImage.path,
              metadata: {
                backend: latestStatus?.backend ?? "unknown",
                plugins_used: latestStatus?.active_plugins ?? [],
              },
              created_at: latestImage.created_at,
            } satisfies GenerateResponse)
          );
        }
      });
    } catch (error) {
      console.error("Failed to load recent images:", error);
    }
  }, []);

  const loadDashboardControls = useCallback(async () => {
    try {
      const [pluginList, runtimeConfig] = await Promise.all([
        api.getPlugins(),
        api.getGenerationConfig(),
      ]);
      startTransition(() => {
        setPlugins(pluginList);
        setGenerationConfig(runtimeConfig);
      });
    } catch (error) {
      console.error("Failed to load dashboard controls:", error);
    }
  }, []);

  const loadGenerationEvents = useCallback(async () => {
    try {
      const response = await api.getGenerationEvents(8);
      startTransition(() => {
        setGenerationEvents(response.events);
      });
    } catch (error) {
      console.error("Failed to load generation events:", error);
    }
  }, []);

  runGenerationRef.current = async (source: "manual" | "loop") => {
    if (isGeneratingRef.current) return;

    const clientRequestId = createClientRequestId(source);
    generationRequestIdRef.current = clientRequestId;
    if (generationResetTimeoutRef.current) {
      clearTimeout(generationResetTimeoutRef.current);
    }
    isGeneratingRef.current = true;
    setIsGenerating(true);
    setGenerationProgress(INITIAL_IMAGE_PROGRESS);
    const activeCadence =
      CADENCE_OPTIONS.find((option) => option.minutes === cadenceMinutesRef.current) ??
      CADENCE_OPTIONS[2];

    addLog(
      source === "manual"
        ? "Generating image now."
        : `Loop tick fired. Next image requested with ${activeCadence.label.toLowerCase()} cadence.`
    );

    try {
      const response = await api.generate({
        prompt: promptSeedRef.current.trim() || undefined,
        enable_plugins: true,
        seed: seed ?? undefined,
        client_request_id: clientRequestId,
      });

      startTransition(() => {
        setCurrentImage(response);
        setSessionCount((count) => count + 1);
      });

      addLog(`Image created with ${response.metadata.backend}.`);
      setGenerationProgress({
        progress: 100,
        title: "Image ready",
        detail: "The generated image is saved and ready to review.",
      });
      if (generationResetTimeoutRef.current) {
        clearTimeout(generationResetTimeoutRef.current);
      }
      generationResetTimeoutRef.current = setTimeout(() => {
        setGenerationProgress(null);
      }, 1200);
      await galleryCache.clear();
      await Promise.all([
        loadRecentImages(),
        loadDashboardControls(),
        loadGenerationEvents(),
        api.getStatus().then(setStatus),
      ]);
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : "Unknown error";
      addLog(`Generation failed: ${errorMsg}`, "error");
      setGenerationProgress(null);
    } finally {
      generationRequestIdRef.current = null;
      isGeneratingRef.current = false;
      setIsGenerating(false);
    }
  };

  useEffect(() => {
    setPromptSeed(readString(STORAGE_KEYS.promptSeed, ""));
    setCadenceMinutes(readNumber(STORAGE_KEYS.cadenceMinutes, 60));
    setLoopEnabled(readBoolean(STORAGE_KEYS.sessionLoop, false));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEYS.promptSeed, promptSeed);
    promptSeedRef.current = promptSeed;
  }, [promptSeed]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEYS.cadenceMinutes, String(cadenceMinutes));
    cadenceMinutesRef.current = cadenceMinutes;
  }, [cadenceMinutes]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEYS.sessionLoop, String(loopEnabled));
  }, [loopEnabled]);

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  useEffect(() => {
    isGeneratingRef.current = isGenerating;
  }, [isGenerating]);

  useEffect(() => {
    api.getStatus().then(setStatus).catch(console.error);
    loadRecentImages();
    loadDashboardControls();
    loadGenerationEvents();

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

      const nextProgress = getTaskProgressUpdate(
        data,
        "image_generation",
        generationRequestIdRef.current
      );
      if (nextProgress) {
        setGenerationProgress((prev) =>
          prev && prev.progress > nextProgress.progress ? prev : nextProgress
        );
      }

      if (typeof data !== "object" || data === null || !("type" in data)) return;

      const msg = data as Record<string, unknown>;
      if (msg.type === "model_loading") {
        addLog(String(msg.message ?? "Loading model..."));
      } else if (msg.type === "generation_completed") {
        addLog(`Saved ${String(msg.image_path ?? "image")}.`);
        void loadGenerationEvents();
      } else if (msg.type === "generation_error") {
        addLog(`Backend error: ${String(msg.error ?? "unknown")}`, "error");
        void loadGenerationEvents();
      }
    });

    return () => {
      unsubscribe();
      if (promptResetTimeoutRef.current) {
        clearTimeout(promptResetTimeoutRef.current);
      }
      if (generationResetTimeoutRef.current) {
        clearTimeout(generationResetTimeoutRef.current);
      }
    };
  }, [loadDashboardControls, loadGenerationEvents, loadRecentImages]);

  useEffect(() => {
    if (!isGenerating || !generationProgress || generationProgress.progress >= 96) return;

    const timeoutId = setTimeout(() => {
      setGenerationProgress((prev) =>
        prev ? getFallbackProgress("image_generation", prev) : prev
      );
    }, 2500);

    return () => clearTimeout(timeoutId);
  }, [generationProgress, isGenerating]);

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
    if (!loopEnabled) {
      setNextRunAt(null);
      return;
    }

    const firstRun = new Date(Date.now() + cadenceMinutes * 60 * 1000);
    setNextRunAt(firstRun);
  }, [loopEnabled, cadenceMinutes]);

  useEffect(() => {
    if (!loopEnabled || !nextRunAt) return;

    const intervalId = window.setInterval(() => {
      setClockTick(Date.now());
      if (Date.now() >= nextRunAt.getTime() && !isGeneratingRef.current) {
        void runGenerationRef.current("loop");
        setNextRunAt(new Date(Date.now() + cadenceMinutes * 60 * 1000));
      }
    }, 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [cadenceMinutes, loopEnabled, nextRunAt]);

  const tabs = [
    { id: "generate" as const, label: "Create", icon: Sparkles },
    { id: "gallery" as const, label: "Gallery", icon: ImageIcon },
    { id: "settings" as const, label: "Settings", icon: SettingsIcon },
  ];

  const generatePromptDraft = async () => {
    const clientRequestId = createClientRequestId("prompt");
    promptRequestIdRef.current = clientRequestId;
    if (promptResetTimeoutRef.current) {
      clearTimeout(promptResetTimeoutRef.current);
    }
    setIsGeneratingPrompt(true);
    setPromptError(null);
    setPromptProgress(INITIAL_PROMPT_PROGRESS);

    try {
      const response = await api.generatePrompt(metaPrompt || undefined, clientRequestId);
      setPromptSeed(response.prompt);
      promptSeedRef.current = response.prompt;
      addLog("Prompt draft generated.");
      setPromptProgress({
        progress: 100,
        title: "Prompt ready",
        detail: "The draft prompt is ready to edit or run.",
      });
      promptResetTimeoutRef.current = setTimeout(() => {
        setPromptProgress(null);
      }, 900);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to generate prompt";
      setPromptError(message);
      addLog(`Prompt generation failed: ${message}`, "error");
      setPromptProgress(null);
    } finally {
      promptRequestIdRef.current = null;
      setIsGeneratingPrompt(false);
    }
  };

  const handleRuntimeConfigChange = (updates: Partial<GenerationConfig>) => {
    setGenerationConfig((current) => (current ? { ...current, ...updates } : current));
  };

  const togglePlugin = async (pluginName: string) => {
    try {
      const response = await api.togglePlugin(pluginName);
      addLog(`${pluginName} ${response.enabled ? "enabled" : "disabled"}.`);
      const [pluginList, refreshedStatus] = await Promise.all([api.getPlugins(), api.getStatus()]);
      startTransition(() => {
        setPlugins(pluginList);
        setStatus(refreshedStatus);
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      addLog(`Failed to update ${pluginName}: ${message}`, "error");
    }
  };

  const updateBackend = async (backend: (typeof DASHBOARD_BACKEND_OPTIONS)[number]["id"]) => {
    try {
      const response = await api.setGenerationConfig({ image_backend: backend });
      const refreshedStatus = await api.getStatus();
      startTransition(() => {
        setGenerationConfig(response.config);
        setStatus(refreshedStatus);
      });
      addLog(`Image backend set to ${backend}.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      addLog(`Failed to change backend: ${message}`, "error");
    }
  };

  return (
    <div className="relative flex h-screen overflow-hidden bg-background">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute inset-x-0 top-0 h-64 bg-[radial-gradient(circle_at_top_left,hsl(var(--primary)/0.16),transparent_36rem)]" />
        <div className="absolute right-0 top-0 h-72 w-72 rounded-full bg-accent/8 blur-3xl" />
      </div>

      <div className="relative z-10 flex h-full w-full flex-col overflow-hidden">
      <header className="border-b border-border/80 bg-card/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-border/80 bg-background/70 shadow-[0_12px_30px_rgba(0,0,0,0.18)]">
              <Image src="/logo_mark.png" alt="DreamGen" width={22} height={22} />
            </div>
            <div>
              <div className="text-base font-semibold tracking-tight text-foreground">DreamGen</div>
              <div className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground/85">
                recurring local image generator
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 text-xs">
            <span className="status-pill">
              <span className={cn("h-1.5 w-1.5 rounded-full", status?.status === "ready" ? "bg-primary" : "bg-amber-400")} />
              {status?.status === "ready" ? "API ready" : "Connecting"}
            </span>
            <span className="status-pill hidden sm:inline-flex">
              GPU {status?.gpu_available ? "online" : "offline"}
            </span>
            <span className="status-pill hidden md:inline-flex capitalize">
              {status?.backend ?? "unknown"}
            </span>
          </div>
        </div>
      </header>

      <div className="border-b border-border/70 bg-muted/20">
        <div className="mx-auto flex max-w-7xl gap-2 overflow-x-auto px-3 py-3 sm:px-6">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex items-center gap-2 rounded-full border px-3 py-2 text-sm transition whitespace-nowrap",
                  activeTab === tab.id
                    ? "border-border/80 bg-card/90 text-foreground shadow-[0_8px_30px_rgba(0,0,0,0.18)]"
                    : "border-transparent text-muted-foreground hover:border-border/60 hover:bg-card/40 hover:text-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      <main className="flex-1 overflow-hidden">
        <AnimatePresence mode="wait">
          {activeTab === "generate" && (
            <motion.div
              key="generate"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="h-full overflow-y-auto"
            >
              <div className="mx-auto max-w-[1600px] px-4 py-4 sm:px-6">
                <div className="ambient-panel rounded-2xl border border-border/80 bg-card/75 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        onClick={() => void runGenerationRef.current("manual")}
                        disabled={isGenerating}
                        className="inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition hover:opacity-95 disabled:opacity-60"
                      >
                        {isGenerating ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Sparkles className="h-4 w-4" />
                        )}
                        {isGenerating
                          ? `Generating ${generationProgress?.progress ?? INITIAL_IMAGE_PROGRESS.progress}%`
                          : "Generate"}
                      </button>
                      <button
                        onClick={() => setLoopEnabled((value) => !value)}
                        className={cn(
                          "inline-flex items-center gap-2 rounded-full border px-4 py-2.5 text-sm font-medium transition",
                          loopEnabled
                            ? "border-destructive/40 bg-destructive/12 text-foreground hover:bg-destructive/18"
                            : "border-border/70 bg-background/75 text-muted-foreground hover:border-primary/30 hover:text-foreground"
                        )}
                      >
                        {loopEnabled ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                        {loopEnabled ? "Stop loop" : "Start loop"}
                      </button>
                    </div>

                    <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2">
                      <span className="status-pill">
                        {promptSeed.trim() ? "Prompt locked" : "Prompt from plugins"}
                      </span>
                      <span className="status-pill">
                        Next: {loopEnabled ? formatCountdown(nextRunAt) : "Not scheduled"}
                      </span>
                      {CADENCE_OPTIONS.map((option) => (
                        <button
                          key={option.minutes}
                          aria-pressed={cadenceMinutes === option.minutes}
                          onClick={() => setCadenceMinutes(option.minutes)}
                          className={cn(
                            "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition",
                            cadenceMinutes === option.minutes
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-border/70 bg-background/70 text-muted-foreground hover:border-primary/30 hover:text-foreground"
                          )}
                        >
                          {cadenceMinutes === option.minutes ? (
                            <Check className="h-3 w-3" />
                          ) : null}
                          {option.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
                  <section className="grid content-start gap-5 lg:grid-cols-[minmax(380px,460px)_minmax(0,1fr)] lg:items-start">
                    <div className="ambient-panel rounded-[2rem] border border-border/80 p-6 lg:col-start-1 lg:row-start-1">
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div>
                          <div className="text-[11px] uppercase tracking-[0.22em] text-primary">
                            One-off prompt
                          </div>
                          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-foreground">
                            Seed the next image.
                          </h1>
                          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                            Leave the field empty for DreamGen to compose a prompt from the active plugins.
                          </p>
                        </div>

                        <div className="flex flex-wrap gap-2">
                          <span className="status-pill capitalize">{currentBackend}</span>
                          <span className="status-pill">{enabledPlugins.length} plugins</span>
                        </div>
                      </div>

                      <div className="mt-4">
                        <div className="mb-2 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                          Plugins
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {plugins.map((plugin) => (
                            <button
                              key={plugin.name}
                              onClick={() => void togglePlugin(plugin.name)}
                              className={cn(
                                "rounded-full border px-3 py-2 text-sm transition",
                                plugin.enabled
                                  ? "border-primary/35 bg-primary/10 text-foreground"
                                  : "border-border/70 bg-background/75 text-muted-foreground hover:border-primary/25 hover:text-foreground"
                              )}
                            >
                              {plugin.name.replaceAll("_", " ")}
                            </button>
                          ))}
                        </div>
                        <div className="mt-2 text-xs leading-6 text-muted-foreground">
                          {selectedBackend === "zimage" && enabledLoras.length > 0
                            ? `LoRA path armed: ${enabledLoras.slice(0, 3).join(", ")}${enabledLoras.length > 3 ? "..." : ""}.`
                            : selectedBackend === "ollama"
                              ? `Ollama image backend${generationConfig?.ollama_image_model ? ` using ${generationConfig.ollama_image_model}` : " using auto model selection"}.`
                              : selectedBackend === "ernie"
                                ? `ERNIE-Image${generationConfig?.ernie_prompt_enhancer === false ? "" : " prompt enhancer"} using ${generationConfig?.ernie_image_model ?? "baidu/ERNIE-Image-Turbo"}.`
                              : "Use Settings for downloads, auth, and deeper model configuration."}
                        </div>
                      </div>

                      <div className="mt-5 grid gap-4">
                        <div className="grid content-start gap-4">
                          <div className="rounded-[1.75rem] border border-border/70 bg-background/82 p-4">
                            <button
                              type="button"
                              onClick={() => setPromptBuilderOpen((value) => !value)}
                              className="flex w-full items-center justify-between gap-3 text-left"
                            >
                              <div className="flex items-center gap-2">
                                <Wand2 className="h-4 w-4 text-primary" />
                                <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                                  Prompt builder
                                </span>
                              </div>
                              {promptBuilderOpen ? (
                                <ChevronDown className="h-4 w-4 text-muted-foreground" />
                              ) : (
                                <ChevronRight className="h-4 w-4 text-muted-foreground" />
                              )}
                            </button>

                            <AnimatePresence initial={false}>
                              {promptBuilderOpen && (
                                <motion.div
                                  initial={{ height: 0, opacity: 0 }}
                                  animate={{ height: "auto", opacity: 1 }}
                                  exit={{ height: 0, opacity: 0 }}
                                  className="overflow-hidden"
                                >
                                  <div className="mt-4 grid gap-3">
                                    <div className="flex flex-wrap gap-2">
                                      <button
                                        type="button"
                                        onClick={() => setShowMetaPromptModal(true)}
                                        className="inline-flex items-center gap-2 rounded-full border border-border/70 px-4 py-2 text-sm text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                                      >
                                        <SettingsIcon className="h-3.5 w-3.5" />
                                        Meta prompt
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => void generatePromptDraft()}
                                        disabled={isGeneratingPrompt}
                                        className="inline-flex items-center gap-2 rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-95 disabled:opacity-60"
                                      >
                                        {isGeneratingPrompt ? (
                                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                        ) : (
                                          <Sparkles className="h-3.5 w-3.5" />
                                        )}
                                        Draft prompt
                                      </button>
                                    </div>

                                    {isGeneratingPrompt && promptProgress && (
                                      <TaskProgress progress={promptProgress} compact />
                                    )}

                                    {promptError && (
                                      <div className="rounded-2xl border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                                        {promptError}
                                      </div>
                                    )}

                                    <div>
                                      <label className="mb-2 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                                        Final prompt
                                      </label>
                                      <textarea
                                        value={promptSeed}
                                        onChange={(event) => setPromptSeed(event.target.value)}
                                        rows={6}
                                        placeholder="Optional: brutalist greenhouse, paper diorama city, weathered arcade shrine..."
                                        className="w-full rounded-[1.25rem] border border-input/85 bg-background/95 px-4 py-4 text-sm leading-6 text-foreground outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                                      />
                                    </div>

                                    <div className="flex flex-wrap items-center justify-between gap-3">
                                      <span className="text-xs leading-6 text-muted-foreground">
                                        {promptSeed.trim()
                                          ? "Ready to run as written."
                                          : "Leave empty to generate from plugins at run time."}
                                      </span>
                                      <button
                                        type="button"
                                        onClick={() => setPromptSeed("")}
                                        className="rounded-full border border-border/70 px-4 py-2 text-sm text-muted-foreground transition hover:border-primary/30 hover:text-foreground"
                                      >
                                        Clear
                                      </button>
                                    </div>
                                  </div>
                                </motion.div>
                              )}
                            </AnimatePresence>
                          </div>

                          <div className="rounded-[1.75rem] border border-border/70 bg-background/80 px-4 py-4">
                            <div className="text-xs uppercase tracking-wide text-muted-foreground">
                              Last activity
                            </div>
                            <div className="mt-2 text-sm leading-6 text-foreground">{lastActivity}</div>
                          </div>
                        </div>

                        <div className="grid content-start gap-4">
                          <div className="rounded-[1.75rem] border border-primary/25 bg-primary/10 p-4">
                            <div className="mb-3 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                              Model pipeline
                            </div>
                            <div className="grid gap-3">
                              <div className="rounded-2xl border border-border/60 bg-background/78 px-3 py-3">
                                <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                                  Stage 1 prompt
                                </div>
                                <div className="mt-1 truncate text-sm font-medium text-foreground" title={promptModelLabel}>
                                  {promptModelLabel}
                                </div>
                              </div>
                              <div className="rounded-2xl border border-border/60 bg-background/78 px-3 py-3">
                                <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                                  Stage 2 image
                                </div>
                                <div className="mt-1 truncate text-sm font-medium text-foreground" title={imageModelLabel}>
                                  {imageModelLabel}
                                </div>
                              </div>
                            </div>
                          </div>

                          <div className="rounded-[1.75rem] border border-border/70 bg-background/82 p-4">
                            <div className="mb-3 flex items-center justify-between gap-3">
                              <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                                Image backend
                              </div>
                              <div className="text-xs text-muted-foreground capitalize">{selectedBackend}</div>
                            </div>
                            <div className="grid grid-cols-2 gap-2">
                              {DASHBOARD_BACKEND_OPTIONS.map((option) => (
                                <button
                                  key={option.id}
                                  onClick={() => void updateBackend(option.id)}
                                  className={cn(
                                    "rounded-2xl border px-3 py-2 text-sm transition",
                                    selectedBackend === option.id
                                      ? "border-primary/40 bg-primary/12 text-foreground"
                                      : "border-border/70 bg-background/75 text-muted-foreground hover:border-primary/30 hover:text-foreground"
                                  )}
                                >
                                  {option.label}
                                </button>
                              ))}
                            </div>
                          </div>

                          <div className="rounded-[1.75rem] border border-border/70 bg-background/82 p-4">
                            <button
                              type="button"
                              onClick={() => setRunControlsOpen((value) => !value)}
                              className="flex w-full items-center justify-between gap-3 text-left"
                            >
                              <div className="flex items-center gap-2">
                                <SlidersHorizontal className="h-4 w-4 text-primary" />
                                <span className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
                                  Run controls
                                </span>
                              </div>
                              {runControlsOpen ? (
                                <ChevronDown className="h-4 w-4 text-muted-foreground" />
                              ) : (
                                <ChevronRight className="h-4 w-4 text-muted-foreground" />
                              )}
                            </button>

                            <AnimatePresence initial={false}>
                              {runControlsOpen && (
                                <motion.div
                                  initial={{ height: 0, opacity: 0 }}
                                  animate={{ height: "auto", opacity: 1 }}
                                  exit={{ height: 0, opacity: 0 }}
                                  className="overflow-hidden"
                                >
                                  <div className="mt-4">
                                    <AdvancedControls
                                      seed={seed}
                                      onSeedChange={setSeed}
                                      onConfigChange={handleRuntimeConfigChange}
                                    />
                                  </div>
                                </motion.div>
                              )}
                            </AnimatePresence>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div className="ambient-panel order-first rounded-[2rem] border border-border/80 p-5 lg:sticky lg:top-4 lg:col-start-2 lg:row-start-1 lg:order-none">
                      <div className="mb-4 flex items-center justify-between gap-4">
                        <div>
                          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                            Current output
                          </div>
                          <div className="mt-1 text-lg font-semibold text-foreground">
                            {currentImage ? "Latest generation" : "Waiting for first image"}
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <span className="status-pill capitalize">{currentBackend}</span>
                          <span className="status-pill">{currentPluginCount} plugins</span>
                          {isSmokeBackend ? <span className="status-pill">smoke-test quality</span> : null}
                        </div>
                      </div>

                      <div className="mb-4 rounded-2xl border border-border/60 bg-background/78 px-4 py-3">
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                          Image location
                        </div>
                        <div className="mt-2 break-all font-mono text-xs leading-5 text-foreground">
                          {currentImage?.image_path ?? "The saved image path appears here after generation."}
                        </div>
                      </div>

                      <div className="min-h-[380px] rounded-[1.5rem] border border-border/70 bg-background/70 p-4">
                        <AnimatePresence mode="wait">
                          {isGenerating ? (
                            <motion.div
                              key="loading"
                              initial={{ opacity: 0, scale: 0.97 }}
                              animate={{ opacity: 1, scale: 1 }}
                              exit={{ opacity: 0, scale: 0.97 }}
                              className="flex min-h-[340px] flex-col items-center justify-center text-center"
                            >
                              <TaskProgress progress={generationProgress ?? INITIAL_IMAGE_PROGRESS} />
                            </motion.div>
                          ) : currentImage ? (
                            <motion.div
                              key={currentImage.id}
                              initial={{ opacity: 0, scale: 0.97 }}
                              animate={{ opacity: 1, scale: 1 }}
                              exit={{ opacity: 0, scale: 0.97 }}
                              className="flex w-full flex-col items-center"
                            >
                              <div className="flex min-h-[320px] w-full items-center justify-center rounded-[1.5rem] border border-border/60 bg-[radial-gradient(circle_at_top,hsl(var(--accent)/0.08),transparent_22rem)] px-4 py-6">
                                {/* Backend-served generated files are not routed through Next image optimization. */}
                                {/* eslint-disable-next-line @next/next/no-img-element */}
                                <img
                                  src={`${API_BASE}${currentImage.image_path}`}
                                  alt="Generated image"
                                  className="max-h-[62vh] max-w-full rounded-2xl object-contain shadow-[0_24px_80px_rgba(0,0,0,0.34)]"
                                />
                              </div>
                              <div className="mt-4 w-full rounded-2xl border border-border/60 bg-background/80 px-4 py-3">
                                <p className="text-sm leading-7 text-muted-foreground">
                                  {currentImage.prompt}
                                </p>
                              </div>
                            </motion.div>
                          ) : (
                            <div className="flex min-h-[340px] flex-col items-center justify-center text-center">
                              <ImageIcon className="mb-4 h-14 w-14 text-muted-foreground/30" />
                              <p className="text-sm text-muted-foreground">
                                Generate once when the prompt and runtime controls are ready.
                              </p>
                            </div>
                          )}
                        </AnimatePresence>
                      </div>
                    </div>
                  </section>

                  <aside className="grid content-start gap-4">
                    <div className="ambient-panel rounded-[1.75rem] border border-border/80 p-5">
                      <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                        Session
                      </div>
                      <div className="mt-4 grid gap-3">
                        <div className="rounded-2xl border border-border/60 bg-background/78 px-4 py-3">
                          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                            <Clock3 className="h-4 w-4 text-primary" />
                            {loopEnabled ? "Loop running" : "Loop stopped"}
                          </div>
                          <div className="mt-2 text-xs leading-6 text-muted-foreground">
                            Next run: {loopEnabled ? formatCountdown(nextRunAt) : "Not scheduled"}
                          </div>
                        </div>

                        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                          <div className="rounded-2xl border border-border/60 bg-background/78 px-4 py-3">
                            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                              Backend
                            </div>
                            <div className="mt-2 text-sm font-medium capitalize text-foreground">
                              {currentBackend}
                            </div>
                          </div>
                          <div className="rounded-2xl border border-border/60 bg-background/78 px-4 py-3">
                            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                              This session
                            </div>
                            <div className="mt-2 text-sm font-medium text-foreground">
                              {sessionCount} images
                            </div>
                          </div>
                        </div>

                        <div className="rounded-2xl border border-border/60 bg-background/78 px-4 py-3">
                          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                            Last activity
                          </div>
                          <div className="mt-2 text-sm leading-6 text-foreground">{lastActivity}</div>
                        </div>

                        <div className="rounded-2xl border border-border/60 bg-background/78 px-4 py-3">
                          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
                            Lifecycle
                          </div>
                          {generationEvents.length > 0 ? (
                            <div className="mt-3 space-y-2">
                              {generationEvents.slice(0, 4).map((event, index) => (
                                <div
                                  key={`${event.timestamp}-${event.id ?? index}-${event.type}`}
                                  className="flex items-start justify-between gap-3 text-xs"
                                >
                                  <span className="min-w-0 capitalize text-foreground">
                                    {describeGenerationEvent(event)}
                                  </span>
                                  <span className="shrink-0 text-muted-foreground">
                                    {new Date(event.timestamp).toLocaleTimeString()}
                                  </span>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="mt-2 text-sm leading-6 text-muted-foreground">
                              No recorded lifecycle events yet.
                            </div>
                          )}
                        </div>
                      </div>

                    </div>

                    <div className="ambient-panel rounded-[1.75rem] border border-border/80 p-5">
                      <div className="mb-4 flex items-center justify-between gap-3">
                        <div>
                          <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                            Recent outputs
                          </div>
                          <h2 className="mt-1 text-lg font-semibold text-foreground">
                            Quick picks
                          </h2>
                        </div>
                      </div>

                      {recentImages.length > 0 ? (
                        <div className="space-y-3">
                          {recentImages.slice(0, 3).map((image) => (
                            <div
                              key={image.path}
                              className="rounded-2xl border border-border/60 bg-background/78 p-3 transition hover:border-primary/35 hover:bg-background/90"
                            >
                              <button
                                onClick={() => {
                                  setCurrentImage({
                                    id: image.path,
                                    prompt: image.prompt,
                                    image_path: image.path,
                                    metadata: {
                                      backend: status?.backend ?? "unknown",
                                      plugins_used: status?.active_plugins ?? [],
                                    },
                                    created_at: image.created_at,
                                  });
                                }}
                                className="flex w-full items-center gap-3 text-left"
                              >
                                {/* Backend-served generated files are not routed through Next image optimization. */}
                                {/* eslint-disable-next-line @next/next/no-img-element */}
                                <img
                                  src={`${API_BASE}${image.path}`}
                                  alt="Recent generation"
                                  className="h-16 w-16 rounded-xl object-cover"
                                />
                                <div className="min-w-0">
                                  <p className="text-xs text-muted-foreground">
                                    {new Date(image.created_at).toLocaleString()}
                                  </p>
                                  <p className="mt-1 text-sm leading-6 text-foreground">
                                    {truncatePrompt(image.prompt, 58)}
                                  </p>
                                </div>
                              </button>
                              <div className="mt-3 flex gap-2">
                                <button
                                  onClick={() => setPromptSeed(image.prompt)}
                                  className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl border border-border/70 px-3 py-2 text-xs text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                                >
                                  <Play className="h-3.5 w-3.5" />
                                  Use prompt
                                </button>
                                <button
                                  onClick={() => {
                                    setPromptSeed(image.prompt);
                                    promptSeedRef.current = image.prompt;
                                    void runGenerationRef.current("manual");
                                  }}
                                  disabled={isGenerating}
                                  className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-primary px-3 py-2 text-xs text-primary-foreground transition hover:opacity-95 disabled:opacity-60"
                                >
                                  <RotateCcw className="h-3.5 w-3.5" />
                                  Rerun
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="rounded-2xl border border-border/60 bg-background/78 px-4 py-8 text-center text-sm text-muted-foreground">
                          No recent images yet.
                        </div>
                      )}
                    </div>
                  </aside>
                </div>
              </div>
            </motion.div>
          )}

          {activeTab === "gallery" && (
            <motion.div
              key="gallery"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="h-full"
            >
              <Gallery />
            </motion.div>
          )}

          {activeTab === "settings" && (
            <motion.div
              key="settings"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="h-full"
            >
              <Settings systemStatus={status} />
            </motion.div>
          )}

        </AnimatePresence>
      </main>

      <footer className="border-t border-border bg-muted/50">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-2 text-xs text-muted-foreground sm:px-6">
          <span>
            {status?.status === "ready" ? "Ready to generate" : "Connecting to backend"}
          </span>
          <span>
            {loopEnabled
              ? `Loop active, next run in ${formatCountdown(nextRunAt)}`
              : "Loop stopped"}
          </span>
        </div>
      </footer>
      </div>

      <MetaPromptModal
        isOpen={showMetaPromptModal}
        onClose={() => setShowMetaPromptModal(false)}
        metaPrompt={metaPrompt}
        onSave={setMetaPrompt}
      />
    </div>
  );
}
