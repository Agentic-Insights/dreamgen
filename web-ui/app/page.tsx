"use client";

import { startTransition, useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import {
  Check,
  Clock3,
  Image as ImageIcon,
  Loader2,
  Play,
  Settings as SettingsIcon,
  Sparkles,
  Square,
  Wand2,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import Gallery from "@/components/Gallery";
import Settings from "@/components/Settings";
import TaskProgress from "@/components/TaskProgress";
import {
  API_BASE,
  api,
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
  type ProgressSnapshot,
} from "@/lib/task-progress";
import { cn } from "@/lib/utils";
import galleryCache from "@/lib/cache";

type TabId = "generate" | "gallery" | "settings" | "playground";

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

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabId>("generate");
  const [promptSeed, setPromptSeed] = useState("");
  const [cadenceMinutes, setCadenceMinutes] = useState(60);
  const [loopEnabled, setLoopEnabled] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationProgress, setGenerationProgress] = useState<ProgressSnapshot | null>(null);
  const [currentImage, setCurrentImage] = useState<GenerateResponse | null>(null);
  const [recentImages, setRecentImages] = useState<RecentImage[]>([]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [generationConfig, setGenerationConfig] = useState<GenerationConfig | null>(null);
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
  const generationRequestIdRef = useRef<string | null>(null);
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
  const lastActivity = logs[logs.length - 1];
  const selectedCadence =
    CADENCE_OPTIONS.find((option) => option.minutes === cadenceMinutes) ?? CADENCE_OPTIONS[2];

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
      await Promise.all([loadRecentImages(), loadDashboardControls(), api.getStatus().then(setStatus)]);
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

    const unsubscribe = api.subscribeWebSocket((data) => {
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
      } else if (msg.type === "generation_error") {
        addLog(`Backend error: ${String(msg.error ?? "unknown")}`, "error");
      }
    });

    return () => {
      unsubscribe();
      if (generationResetTimeoutRef.current) {
        clearTimeout(generationResetTimeoutRef.current);
      }
    };
  }, [loadDashboardControls, loadRecentImages]);

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
    { id: "playground" as const, label: "Advanced", icon: Wand2 },
  ];

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
              <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="ambient-panel rounded-2xl border border-primary/35 bg-primary/10 p-5">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.22em] text-primary">
                          Ad-hoc
                        </div>
                        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
                          Generate once
                        </h2>
                      </div>
                      <Sparkles className="h-5 w-5 text-primary" />
                    </div>
                    <div className="mt-4 flex flex-wrap items-center gap-3">
                      <button
                        onClick={() => void runGenerationRef.current("manual")}
                        disabled={isGenerating}
                        className="inline-flex items-center gap-2 rounded-full bg-primary px-5 py-3 text-sm font-medium text-primary-foreground transition hover:opacity-95 disabled:opacity-60"
                      >
                        {isGenerating ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Sparkles className="h-4 w-4" />
                        )}
                        {isGenerating
                          ? `Generating ${generationProgress?.progress ?? INITIAL_IMAGE_PROGRESS.progress}%`
                          : "Generate once"}
                      </button>
                      <span className="text-xs text-muted-foreground">
                        {promptSeed.trim() ? "Using prompt seed" : "Using generated prompt"}
                      </span>
                    </div>
                  </div>

                  <div
                    className={cn(
                      "ambient-panel rounded-2xl border p-5",
                      loopEnabled
                        ? "border-destructive/35 bg-destructive/10"
                        : "border-border/80 bg-card/70"
                    )}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
                          Schedule
                        </div>
                        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
                          Scheduled loop
                        </h2>
                        <div className="mt-2 inline-flex rounded-full border border-primary/35 bg-primary/10 px-3 py-1 text-xs font-medium text-foreground">
                          Cadence: {selectedCadence.label}
                        </div>
                      </div>
                      {loopEnabled ? (
                        <Square className="h-5 w-5 text-foreground" />
                      ) : (
                        <Play className="h-5 w-5 text-foreground" />
                      )}
                    </div>
                    <div className="mt-4 flex flex-wrap items-center gap-3">
                      <button
                        onClick={() => setLoopEnabled((value) => !value)}
                        className={cn(
                          "inline-flex items-center gap-2 rounded-full px-5 py-3 text-sm font-medium transition",
                          loopEnabled
                            ? "bg-destructive text-destructive-foreground hover:opacity-95"
                            : "bg-foreground text-background hover:opacity-95"
                        )}
                      >
                        {loopEnabled ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                        {loopEnabled ? "Stop schedule" : "Start schedule"}
                      </button>
                      <span className="text-xs text-muted-foreground">
                        Next run: {loopEnabled ? formatCountdown(nextRunAt) : "Not scheduled"}
                      </span>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {CADENCE_OPTIONS.map((option) => (
                        <button
                          key={option.minutes}
                          aria-pressed={cadenceMinutes === option.minutes}
                          onClick={() => setCadenceMinutes(option.minutes)}
                          className={cn(
                            "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition",
                            cadenceMinutes === option.minutes
                              ? "border-primary bg-primary text-primary-foreground shadow-[0_0_0_3px_hsl(var(--primary)/0.16)]"
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
                  <section className="grid content-start gap-5">
                    <div className="ambient-panel rounded-[2rem] border border-border/80 p-6">
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
                              : "Use Settings for downloads, auth, and deeper model configuration."}
                        </div>
                      </div>

                      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.9fr)]">
                        <div className="grid content-start gap-4">
                          <div>
                            <label className="mb-2 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                              Prompt seed
                            </label>
                            <textarea
                              value={promptSeed}
                              onChange={(event) => setPromptSeed(event.target.value)}
                              rows={5}
                              placeholder="Optional: brutalist greenhouse, paper diorama city, weathered arcade shrine..."
                              className="w-full rounded-[1.75rem] border border-input/85 bg-background/95 px-4 py-4 text-sm leading-6 text-foreground outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
                            />
                          </div>

                          <div className="rounded-[1.75rem] border border-border/70 bg-background/80 px-4 py-4">
                            <div className="text-sm text-foreground">
                              {promptSeed.trim()
                                ? "The one-off action will use this prompt seed."
                                : "The one-off action will request a generated prompt."}
                            </div>
                            <div className="mt-2 text-xs leading-6 text-muted-foreground">
                              Last activity: {lastActivity}
                            </div>
                          </div>

                          <div className="flex flex-wrap gap-2">
                            <button
                              onClick={() => setPromptSeed("")}
                              className="rounded-full border border-border/70 px-4 py-3 text-sm text-muted-foreground transition hover:border-primary/30 hover:text-foreground"
                            >
                              Clear prompt
                            </button>
                          </div>
                        </div>

                        <div className="grid content-start gap-4">
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
                        </div>
                      </div>
                    </div>

                    <div className="ambient-panel rounded-[2rem] border border-border/80 p-5">
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
                            <button
                              key={image.path}
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
                              className="flex w-full items-center gap-3 rounded-2xl border border-border/60 bg-background/78 p-3 text-left transition hover:border-primary/35 hover:bg-background/90"
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

          {activeTab === "playground" && (
            <motion.div
              key="playground"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="h-full"
            >
              <iframe src="/playground" className="h-full w-full border-0" title="Advanced playground" />
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
    </div>
  );
}
