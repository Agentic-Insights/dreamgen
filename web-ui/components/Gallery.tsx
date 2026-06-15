"use client";
/* eslint-disable @next/next/no-img-element */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Trash2, Download, X, Loader2, Clock, FileText, Copy, Check,
  Calendar, Grid, ChevronLeft, ChevronRight, Folder, Star, Eye, EyeOff, Archive,
  UploadCloud, ExternalLink, Info
} from "lucide-react";
import {
  api,
  API_BASE,
  type GalleryCatalogEntry,
  type GalleryFacets,
  type GallerySyncStatus,
  type PublicationState,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import galleryCache from "@/lib/cache";

interface GalleryImage {
  path: string;
  catalog_path: string;
  prompt: string;
  created_at: string;
  size: number;
  metadata: Record<string, unknown>;
  publication: {
    id: string;
    state: PublicationState;
    publishable: boolean;
    quality_flags: string[];
  };
}

interface GalleryResponse {
  images: GalleryImage[];
  total: number;
  limit: number;
  offset: number;
}

interface WeekGroup {
  year: number;
  week: number;
  startDate: Date;
  endDate: Date;
  images: GalleryImage[];
}

type ViewMode = "week" | "all";
type CatalogFilter = PublicationState | "all";

const ALL_PAGE_SIZE = 20;
const WEEK_PAGE_SIZE = 200;
const CACHE_TIMEOUT_MS = 800;
const GALLERY_TIMEOUT_MS = 30000;
const PUBLICATION_OPTIONS: Array<{
  state: PublicationState;
  label: string;
  icon: typeof Star;
}> = [
  { state: "featured", label: "Featured", icon: Star },
  { state: "published", label: "Published", icon: Eye },
  { state: "draft", label: "Draft", icon: FileText },
  { state: "hidden", label: "Hidden", icon: EyeOff },
  { state: "rejected", label: "Rejected", icon: Archive },
];

const stateStyles: Record<PublicationState, string> = {
  featured: "bg-amber-500 text-black",
  published: "bg-emerald-600 text-white",
  draft: "bg-slate-500 text-white",
  hidden: "bg-zinc-700 text-white",
  rejected: "bg-rose-700 text-white",
};

const toGalleryImage = (entry: GalleryCatalogEntry): GalleryImage => ({
  path: entry.image_url || `/images/${entry.path}`,
  catalog_path: entry.path,
  prompt: entry.prompt || "",
  created_at: entry.created_at,
  size: entry.size || 0,
  metadata: entry.metadata || {},
  publication: {
    id: entry.id,
    state: entry.publication_state,
    publishable: entry.publishable,
    quality_flags: entry.quality_flags || [],
  },
});

const withTimeout = async <T,>(
  promise: Promise<T>,
  timeoutMs: number,
  fallback: T
): Promise<T> => (
  new Promise((resolve) => {
    let settled = false;
    const timeoutId = setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve(fallback);
    }, timeoutMs);

    promise
      .then((value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeoutId);
        resolve(value);
      })
      .catch(() => {
        if (settled) return;
        settled = true;
        clearTimeout(timeoutId);
        resolve(fallback);
      });
  })
);

export default function Gallery() {
  const [images, setImages] = useState<GalleryImage[]>([]);
  const [weekGroups, setWeekGroups] = useState<WeekGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedImage, setSelectedImage] = useState<GalleryImage | null>(null);
  const [expandedWeeks, setExpandedWeeks] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [publicationUpdating, setPublicationUpdating] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("week");
  const [catalogFilter, setCatalogFilter] = useState<CatalogFilter>("all");
  const [backendFilter, setBackendFilter] = useState("all");
  const [modelFilter, setModelFilter] = useState("all");
  const [promptFamilyFilter, setPromptFamilyFilter] = useState("all");
  const [qualityFlagFilter, setQualityFlagFilter] = useState("all");
  const [facets, setFacets] = useState<GalleryFacets | null>(null);
  const [syncStatus, setSyncStatus] = useState<GallerySyncStatus | null>(null);
  const [copiedPromptPath, setCopiedPromptPath] = useState<string | null>(null);
  const loadRequestRef = useRef(0);

  const imagesPerPage = viewMode === "all" ? ALL_PAGE_SIZE : WEEK_PAGE_SIZE;
  const selectedImageIndex = selectedImage
    ? images.findIndex((image) => image.catalog_path === selectedImage.catalog_path)
    : -1;
  const canNavigateSelectedImage = selectedImageIndex >= 0 && images.length > 1;

  const organizeByWeek = useCallback((images: GalleryImage[]) => {
    const groups = new Map<string, WeekGroup>();

    images.forEach(image => {
      const date = new Date(image.created_at);
      const year = date.getFullYear();
      const weekNumber = getWeekNumber(date);
      const key = `${year}-${weekNumber}`;

      if (!groups.has(key)) {
        const { start, end } = getWeekBounds(year, weekNumber);
        groups.set(key, {
          year,
          week: weekNumber,
          startDate: start,
          endDate: end,
          images: []
        });
      }

      groups.get(key)!.images.push(image);
    });

    // Sort groups by year and week (newest first)
    const sorted = Array.from(groups.values()).sort((a, b) => {
      if (a.year !== b.year) return b.year - a.year;
      return b.week - a.week;
    });

    setWeekGroups(sorted);

    // Auto-expand the most recent week
    if (sorted.length > 0) {
      const mostRecent = `${sorted[0].year}-${sorted[0].week}`;
      setExpandedWeeks(new Set([mostRecent]));
    }
  }, []);

  const loadImages = useCallback(async () => {
    const requestId = loadRequestRef.current + 1;
    loadRequestRef.current = requestId;
    const limit = viewMode === "all" ? ALL_PAGE_SIZE : WEEK_PAGE_SIZE;
    const offset = viewMode === "all" ? page * ALL_PAGE_SIZE : 0;
    const cacheKey = [
      "gallery_catalog",
      viewMode,
      catalogFilter,
      backendFilter,
      modelFilter,
      promptFamilyFilter,
      qualityFlagFilter,
      page,
      limit,
    ].join("_");

    setLoading(true);
    setError(null);

    try {
      console.log('Fetching gallery catalog from API');
      const [catalogResponse, publishStatus, facetResponse] = await Promise.all([
        api.getGalleryCatalog(limit, offset, catalogFilter, GALLERY_TIMEOUT_MS, {
          backend: backendFilter === "all" ? undefined : backendFilter,
          model: modelFilter === "all" ? undefined : modelFilter,
          prompt_family: promptFamilyFilter === "all" ? undefined : promptFamilyFilter,
          quality_flag: qualityFlagFilter === "all" ? undefined : qualityFlagFilter,
        }),
        api.getGallerySyncStatus(10),
        api.getGalleryFacets(),
      ]);

      if (loadRequestRef.current !== requestId) return;
      const response: GalleryResponse = {
        images: catalogResponse.assets.map(toGalleryImage),
        total: catalogResponse.total,
        limit: catalogResponse.limit,
        offset: catalogResponse.offset,
      };

      void withTimeout(galleryCache.set(cacheKey, {
        images: response.images,
        total: response.total,
        limit: response.limit,
        offset: response.offset,
      }), CACHE_TIMEOUT_MS, undefined);

      setImages(response.images);
      setTotal(response.total);
      setSyncStatus(publishStatus);
      setFacets(facetResponse);

      if (viewMode === "week") {
        organizeByWeek(response.images);
      }
    } catch (err) {
      console.error('Gallery load error:', err);

      const cachedData = await withTimeout(
        galleryCache.get<GalleryResponse>(cacheKey),
        CACHE_TIMEOUT_MS,
        null
      );

      if (loadRequestRef.current !== requestId) return;

      if (cachedData && cachedData.total > 0) {
        console.log('API failed, using cached data');
        setImages(cachedData.images);
        setTotal(cachedData.total);

        if (viewMode === "week") {
          organizeByWeek(cachedData.images);
        }
        setError(null);
      } else {
        const message = err instanceof Error ? err.message : "Unknown error";
        setError(`Failed to load gallery catalog. ${message}`);
      }
    } finally {
      if (loadRequestRef.current === requestId) {
        setLoading(false);
      }
    }
  }, [
    backendFilter,
    catalogFilter,
    modelFilter,
    organizeByWeek,
    page,
    promptFamilyFilter,
    qualityFlagFilter,
    viewMode,
  ]);

  const getWeekNumber = (date: Date): number => {
    const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
    const dayNum = d.getUTCDay() || 7;
    d.setUTCDate(d.getUTCDate() + 4 - dayNum);
    const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    return Math.ceil((((d.getTime() - yearStart.getTime()) / 86400000) + 1) / 7);
  };

  const getWeekBounds = (year: number, week: number): { start: Date; end: Date } => {
    const jan1 = new Date(year, 0, 1);
    const daysToMonday = (jan1.getDay() === 0 ? 6 : jan1.getDay() - 1);
    const firstMonday = new Date(year, 0, 1 - daysToMonday);

    const start = new Date(firstMonday);
    start.setDate(start.getDate() + (week - 1) * 7);

    const end = new Date(start);
    end.setDate(end.getDate() + 6);

    return { start, end };
  };

  const toggleWeek = (weekKey: string) => {
    const newExpanded = new Set(expandedWeeks);
    if (newExpanded.has(weekKey)) {
      newExpanded.delete(weekKey);
    } else {
      newExpanded.add(weekKey);
    }
    setExpandedWeeks(newExpanded);
  };

  useEffect(() => {
    void loadImages();
  }, [loadImages]);

  useEffect(() => {
    setPage(0);
  }, [backendFilter, catalogFilter, modelFilter, promptFamilyFilter, qualityFlagFilter, viewMode]);

  const getImageUrl = (imagePath: string) => `${API_BASE}${imagePath}`;

  const selectAdjacentImage = useCallback((direction: -1 | 1) => {
    if (!selectedImage || images.length <= 1) return;

    const currentIndex = images.findIndex((image) => (
      image.catalog_path === selectedImage.catalog_path
    ));
    if (currentIndex < 0) return;

    const nextIndex = (currentIndex + direction + images.length) % images.length;
    setSelectedImage(images[nextIndex]);
  }, [images, selectedImage]);

  useEffect(() => {
    if (!selectedImage) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelectedImage(null);
      } else if (event.key === "ArrowLeft") {
        selectAdjacentImage(-1);
      } else if (event.key === "ArrowRight") {
        selectAdjacentImage(1);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectAdjacentImage, selectedImage]);

  const handleDelete = async (imagePath: string, event: React.MouseEvent) => {
    event.stopPropagation();
    if (!confirm("Are you sure you want to delete this image?")) return;

    setDeleting(imagePath);
    try {
      const pathParts = imagePath.split("/images/");
      const relativePath = pathParts[1] || imagePath;
      await api.deleteImage(relativePath);

      // Clear cache after deletion
      await withTimeout(galleryCache.clear(), CACHE_TIMEOUT_MS, undefined);

      await loadImages();
      if (selectedImage?.path === imagePath) {
        setSelectedImage(null);
      }
    } catch (err) {
      console.error("Failed to delete image:", err);
      alert("Failed to delete image");
    } finally {
      setDeleting(null);
    }
  };

  const handlePublicationChange = async (
    image: GalleryImage,
    state: PublicationState,
    event?: React.MouseEvent
  ) => {
    event?.stopPropagation();
    const updateKey = `${image.catalog_path}:${state}`;
    setPublicationUpdating(updateKey);
    try {
      const updatedEntry = await api.updatePublicationState(image.catalog_path, state);
      const updatedImage = toGalleryImage(updatedEntry);

      setImages((currentImages) => currentImages.map((item) => (
        item.catalog_path === image.catalog_path ? updatedImage : item
      )));
      setSelectedImage((currentImage) => (
        currentImage?.catalog_path === image.catalog_path ? updatedImage : currentImage
      ));

      await withTimeout(galleryCache.clear(), CACHE_TIMEOUT_MS, undefined);
      await loadImages();
    } catch (err) {
      console.error("Failed to update publication state:", err);
      const message = err instanceof Error ? err.message : "Failed to update publication state";
      alert(message);
    } finally {
      setPublicationUpdating(null);
    }
  };

  const handleDownload = (imagePath: string, prompt: string, event: React.MouseEvent) => {
    event.stopPropagation();
    const link = document.createElement("a");
    link.href = getImageUrl(imagePath);
    const filename = imagePath.split("/").pop() || "image.png";
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleCopyPrompt = async (image: GalleryImage, event: React.MouseEvent) => {
    event.stopPropagation();
    if (!image.prompt.trim()) return;

    try {
      await navigator.clipboard.writeText(image.prompt);
      setCopiedPromptPath(image.catalog_path);
      window.setTimeout(() => {
        setCopiedPromptPath((currentPath) => (
          currentPath === image.catalog_path ? null : currentPath
        ));
      }, 1600);
    } catch (err) {
      console.error("Failed to copy prompt:", err);
      alert("Failed to copy prompt");
    }
  };

  const handleOpenOriginal = (image: GalleryImage, event: React.MouseEvent) => {
    event.stopPropagation();
    window.open(getImageUrl(image.path), "_blank", "noopener,noreferrer");
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const formatDateRange = (start: Date, end: Date) => {
    const options: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
    return `${start.toLocaleDateString("en-US", options)} - ${end.toLocaleDateString("en-US", options)}`;
  };

  const formatSize = (bytes: number) => {
    if (bytes <= 0) return "Unknown size";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatMetadataValue = (value: unknown) => {
    if (value === null || value === undefined || value === "") return "n/a";
    if (typeof value === "boolean") return value ? "yes" : "no";
    if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
    return String(value);
  };

  const getMetadataRows = (image: GalleryImage) => {
    const preferredKeys = [
      "backend",
      "configured_backend",
      "model",
      "device",
      "seed",
      "width",
      "height",
      "steps",
      "num_inference_steps",
      "guidance_scale",
      "true_cfg_scale",
    ];

    return preferredKeys
      .filter((key) => Object.prototype.hasOwnProperty.call(image.metadata, key))
      .map((key) => ({
        key,
        label: key.replaceAll("_", " "),
        value: formatMetadataValue(image.metadata[key]),
      }));
  };

  const getExperimentRows = (image: GalleryImage) => {
    const experiment = image.metadata.experiment;
    if (!experiment || typeof experiment !== "object") return [];
    const data = experiment as {
      id?: string;
      label?: string | null;
      prompt_family?: string | null;
      diagnostic?: boolean;
      pipeline?: { resolved_backend?: string; model?: string; prompt_model?: string };
      parameters?: {
        seed?: number | null;
        width?: number | null;
        height?: number | null;
        steps?: number | null;
        guidance_scale?: number | null;
        true_cfg_scale?: number | null;
      };
      timing?: { generation_seconds?: number };
      enhancers?: { plugins?: string[]; loras?: string[] };
    };
    const parameters = data.parameters ?? {};
    const pipeline = data.pipeline ?? {};
    const timing = data.timing ?? {};
    const enhancers = data.enhancers ?? {};

    return [
      { key: "id", label: "run id", value: data.id },
      { key: "label", label: "label", value: data.label },
      { key: "prompt_family", label: "prompt family", value: data.prompt_family },
      { key: "backend", label: "backend", value: pipeline.resolved_backend },
      { key: "model", label: "model", value: pipeline.model },
      { key: "prompt_model", label: "prompt model", value: pipeline.prompt_model },
      { key: "seed", label: "seed", value: parameters.seed },
      {
        key: "size",
        label: "size",
        value:
          parameters.width && parameters.height
            ? `${parameters.width} x ${parameters.height}`
            : undefined,
      },
      { key: "steps", label: "steps", value: parameters.steps },
      { key: "guidance", label: "guidance", value: parameters.guidance_scale },
      { key: "true_cfg", label: "true cfg", value: parameters.true_cfg_scale },
      {
        key: "generation_time",
        label: "time",
        value:
          typeof timing.generation_seconds === "number"
            ? `${timing.generation_seconds.toFixed(2)}s`
            : undefined,
      },
      {
        key: "plugins",
        label: "plugins",
        value: enhancers.plugins?.length ? enhancers.plugins.join(", ") : undefined,
      },
      {
        key: "loras",
        label: "loras",
        value: enhancers.loras?.length ? enhancers.loras.join(", ") : undefined,
      },
      { key: "diagnostic", label: "diagnostic", value: data.diagnostic },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  };

  const selectedMetadataRows = selectedImage ? getMetadataRows(selectedImage) : [];
  const selectedExperimentRows = selectedImage ? getExperimentRows(selectedImage) : [];

  const renderStateBadge = (state: PublicationState, className?: string) => (
    <span
      className={cn(
        "inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium capitalize",
        stateStyles[state],
        className
      )}
    >
      {state}
    </span>
  );

  const renderImageGrid = (images: GalleryImage[]) => (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2 sm:gap-3 lg:gap-4">
      {images.map((image) => (
        <motion.div
          key={image.path}
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="group relative aspect-square bg-card border border-border rounded-lg overflow-hidden cursor-pointer hover:border-primary transition-colors"
          onClick={() => setSelectedImage(image)}
        >
          <img
            src={getImageUrl(image.path)}
            alt={image.prompt}
            className="w-full h-full object-cover"
            loading="lazy"
          />
          <div className="absolute left-2 top-2">
            {renderStateBadge(image.publication.state, "shadow-sm")}
          </div>

          <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="absolute bottom-0 left-0 right-0 p-3">
              <p className="text-xs text-white line-clamp-2 mb-2">{image.prompt}</p>
              <div className="flex gap-2">
                <button
                  onClick={(e) => handleDelete(image.path, e)}
                  className="p-1.5 bg-destructive/80 hover:bg-destructive rounded text-white"
                  disabled={deleting === image.path}
                >
                  {deleting === image.path ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="w-3.5 h-3.5" />
                  )}
                </button>
                <button
                  onClick={(e) => handleDownload(image.path, image.prompt, e)}
                  className="p-1.5 bg-primary/80 hover:bg-primary rounded text-primary-foreground"
                  title="Download image"
                >
                  <Download className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={(e) => handlePublicationChange(image, "featured", e)}
                  className="p-1.5 bg-amber-500/90 hover:bg-amber-500 rounded text-black disabled:opacity-50"
                  disabled={
                    image.publication.state === "featured"
                    || publicationUpdating === `${image.catalog_path}:featured`
                  }
                  title="Mark featured"
                >
                  {publicationUpdating === `${image.catalog_path}:featured` ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Star className="w-3.5 h-3.5" />
                  )}
                </button>
              </div>
            </div>
          </div>

          <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="bg-black/60 backdrop-blur-sm rounded px-2 py-1">
              <p className="text-xs text-white">{formatSize(image.size)}</p>
            </div>
          </div>
        </motion.div>
      ))}
    </div>
  );

  if (loading && images.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin text-primary mx-auto mb-4" />
          <p className="text-sm text-muted-foreground">Loading gallery...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-destructive mb-4">{error}</p>
          <button
            onClick={loadImages}
            className="px-4 py-2 bg-primary text-primary-foreground rounded hover:opacity-90"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (images.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <FileText className="w-16 h-16 text-muted-foreground/30 mx-auto mb-4" />
          <p className="text-sm text-muted-foreground">No images generated yet</p>
          <p className="text-xs text-muted-foreground mt-1">Start generating to build your gallery</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="h-full flex flex-col">
        {/* Header */}
        <div className="px-4 sm:px-6 py-4 border-b border-border">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <h2 className="text-lg font-semibold">Gallery</h2>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                <span>{total} cataloged images</span>
                {syncStatus && (
                  <span className="inline-flex items-center gap-1.5 rounded border border-border px-2 py-1 text-xs">
                    <UploadCloud className="h-3.5 w-3.5" />
                    {syncStatus.ready
                      ? `${syncStatus.upload_images} approved / ${syncStatus.upload_files} files ready`
                      : syncStatus.message}
                  </span>
                )}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={catalogFilter}
                onChange={(event) => setCatalogFilter(event.target.value as CatalogFilter)}
                className="h-8 rounded-md border border-border bg-background px-2 text-sm"
                title="Filter by publication state"
              >
                <option value="all">All states</option>
                {PUBLICATION_OPTIONS.map((option) => (
                  <option key={option.state} value={option.state}>
                    {option.label}
                  </option>
                ))}
              </select>

              <select
                value={backendFilter}
                onChange={(event) => setBackendFilter(event.target.value)}
                className="h-8 rounded-md border border-border bg-background px-2 text-sm"
                title="Filter by backend"
              >
                <option value="all">All backends</option>
                {(facets?.backends ?? []).map((backend) => (
                  <option key={backend} value={backend}>
                    {backend}
                  </option>
                ))}
              </select>

              <select
                value={modelFilter}
                onChange={(event) => setModelFilter(event.target.value)}
                className="h-8 max-w-[180px] rounded-md border border-border bg-background px-2 text-sm"
                title="Filter by model"
              >
                <option value="all">All models</option>
                {(facets?.models ?? []).map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>

              <select
                value={promptFamilyFilter}
                onChange={(event) => setPromptFamilyFilter(event.target.value)}
                className="h-8 rounded-md border border-border bg-background px-2 text-sm"
                title="Filter by prompt family"
              >
                <option value="all">All families</option>
                {(facets?.prompt_families ?? []).map((family) => (
                  <option key={family} value={family}>
                    {family}
                  </option>
                ))}
              </select>

              <select
                value={qualityFlagFilter}
                onChange={(event) => setQualityFlagFilter(event.target.value)}
                className="h-8 rounded-md border border-border bg-background px-2 text-sm"
                title="Filter by quality flag"
              >
                <option value="all">All flags</option>
                {(facets?.quality_flags ?? []).map((flag) => (
                  <option key={flag} value={flag}>
                    {flag}
                  </option>
                ))}
              </select>

              {/* View Mode Toggle */}
              <div className="flex bg-muted rounded-md p-1">
                <button
                  onClick={() => setViewMode("week")}
                  className={cn(
                    "px-3 py-1 rounded text-sm transition-colors flex items-center gap-1.5",
                    viewMode === "week"
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  <Calendar className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">Week</span>
                </button>
                <button
                  onClick={() => setViewMode("all")}
                  className={cn(
                    "px-3 py-1 rounded text-sm transition-colors flex items-center gap-1.5",
                    viewMode === "all"
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  <Grid className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">All</span>
                </button>
              </div>

              <button
                onClick={async () => {
                  await withTimeout(galleryCache.clear(), CACHE_TIMEOUT_MS, undefined);
                  void loadImages();
                }}
                className="text-sm text-muted-foreground hover:text-foreground"
                disabled={loading}
                title="Refresh gallery (clears cache)"
              >
                {loading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  "Refresh"
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto p-3 sm:p-4 lg:p-6">
          {viewMode === "week" ? (
            // Week View
            <div className="space-y-4">
              {weekGroups.map((group) => {
                const weekKey = `${group.year}-${group.week}`;
                const isExpanded = expandedWeeks.has(weekKey);

                return (
                  <motion.div
                    key={weekKey}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-card border border-border rounded-lg overflow-hidden"
                  >
                    {/* Week Header */}
                    <button
                      onClick={() => toggleWeek(weekKey)}
                      className="w-full px-4 py-3 flex items-center justify-between hover:bg-muted/50 transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <motion.div
                          animate={{ rotate: isExpanded ? 90 : 0 }}
                          transition={{ duration: 0.2 }}
                        >
                          <ChevronRight className="w-4 h-4 text-muted-foreground" />
                        </motion.div>
                        <Folder className="w-4 h-4 text-primary" />
                        <div className="text-left">
                          <div className="font-medium text-sm">
                            Week {group.week}, {group.year}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {formatDateRange(group.startDate, group.endDate)} • {group.images.length} images
                          </div>
                        </div>
                      </div>

                      {/* Preview thumbnails */}
                      <div className="flex -space-x-2">
                        {group.images.slice(0, 3).map((img, idx) => (
                          <div
                            key={idx}
                            className="w-8 h-8 rounded border-2 border-background overflow-hidden"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <img
                              src={getImageUrl(img.path)}
                              alt=""
                              className="w-full h-full object-cover"
                            />
                          </div>
                        ))}
                        {group.images.length > 3 && (
                          <div className="w-8 h-8 rounded border-2 border-background bg-muted flex items-center justify-center">
                            <span className="text-xs text-muted-foreground">+{group.images.length - 3}</span>
                          </div>
                        )}
                      </div>
                    </button>

                    {/* Week Content */}
                    <AnimatePresence>
                      {isExpanded && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.3 }}
                          className="px-4 pb-4"
                        >
                          {renderImageGrid(group.images)}
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                );
              })}
            </div>
          ) : (
            // All View
            renderImageGrid(images)
          )}
        </div>

        {/* Pagination - Only for "All" view */}
        {viewMode === "all" && total > imagesPerPage && (
          <div className="px-6 py-3 border-t border-border">
            <div className="flex items-center justify-between">
              <button
                onClick={() => setPage(Math.max(0, page - 1))}
                disabled={page === 0}
                className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Previous
              </button>
              <span className="text-sm text-muted-foreground">
                Page {page + 1} of {Math.ceil(total / imagesPerPage)}
              </span>
              <button
                onClick={() => setPage(page + 1)}
                disabled={(page + 1) * imagesPerPage >= total}
                className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      <AnimatePresence>
        {selectedImage && (
          <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/82 p-2 backdrop-blur-sm sm:p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setSelectedImage(null)}
            role="dialog"
            aria-modal="true"
            aria-label="Gallery image preview"
          >
            <motion.div
              className="grid h-full max-h-[94vh] w-full max-w-7xl overflow-hidden rounded-lg border border-border bg-background shadow-2xl lg:grid-cols-[minmax(0,1fr)_380px]"
              initial={{ opacity: 0, scale: 0.98, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.98, y: 10 }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="relative flex min-h-[45vh] items-center justify-center bg-black">
                <div className="absolute left-3 top-3 z-10 flex items-center gap-2">
                  {renderStateBadge(selectedImage.publication.state, "shadow-sm")}
                  {selectedImageIndex >= 0 && (
                    <span className="rounded bg-black/65 px-2 py-1 text-xs text-white">
                      {selectedImageIndex + 1} / {images.length}
                    </span>
                  )}
                </div>

                {canNavigateSelectedImage && (
                  <>
                    <button
                      onClick={(event) => {
                        event.stopPropagation();
                        selectAdjacentImage(-1);
                      }}
                      className="absolute left-3 top-1/2 z-10 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/65 text-white transition hover:bg-black/85"
                      title="Previous image"
                      aria-label="Previous image"
                    >
                      <ChevronLeft className="h-5 w-5" />
                    </button>
                    <button
                      onClick={(event) => {
                        event.stopPropagation();
                        selectAdjacentImage(1);
                      }}
                      className="absolute right-3 top-1/2 z-10 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/65 text-white transition hover:bg-black/85"
                      title="Next image"
                      aria-label="Next image"
                    >
                      <ChevronRight className="h-5 w-5" />
                    </button>
                  </>
                )}

                <img
                  src={getImageUrl(selectedImage.path)}
                  alt={selectedImage.prompt}
                  className="max-h-full max-w-full object-contain"
                />
              </div>

              <aside className="flex min-h-0 flex-col border-t border-border bg-background lg:border-l lg:border-t-0">
                <div className="flex items-start justify-between gap-3 border-b border-border p-4">
                  <div className="min-w-0">
                    <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-[0.16em] text-muted-foreground">
                      <Info className="h-3.5 w-3.5" />
                      Review
                    </div>
                    <p className="line-clamp-4 text-sm font-medium leading-6 text-foreground">
                      {selectedImage.prompt || "No prompt saved for this image."}
                    </p>
                  </div>
                  <button
                    onClick={() => setSelectedImage(null)}
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground transition hover:bg-muted hover:text-foreground"
                    title="Close preview"
                    aria-label="Close preview"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto p-4">
                  <div className="grid gap-3 text-sm">
                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-md border border-border bg-muted/30 p-3">
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Created</div>
                        <div className="mt-1 flex items-center gap-1.5 text-xs text-foreground">
                          <Clock className="h-3.5 w-3.5 text-primary" />
                          {formatDate(selectedImage.created_at)}
                        </div>
                      </div>
                      <div className="rounded-md border border-border bg-muted/30 p-3">
                        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">File</div>
                        <div className="mt-1 truncate text-xs text-foreground">{formatSize(selectedImage.size)}</div>
                      </div>
                    </div>

                    <div className="rounded-md border border-border bg-muted/30 p-3">
                      <div className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">Path</div>
                      <div className="break-all font-mono text-xs text-foreground">{selectedImage.catalog_path}</div>
                    </div>

                    <div className="rounded-md border border-border bg-muted/30 p-3">
                      <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-wide text-muted-foreground">
                        <span>Publication</span>
                        {!selectedImage.publication.publishable && (
                          <span className="rounded border border-border px-2 py-0.5 normal-case tracking-normal">
                            not publishable
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {PUBLICATION_OPTIONS.map((option) => {
                          const Icon = option.icon;
                          const updateKey = `${selectedImage.catalog_path}:${option.state}`;
                          const isCurrent = selectedImage.publication.state === option.state;
                          return (
                            <button
                              key={option.state}
                              onClick={(event) => handlePublicationChange(selectedImage, option.state, event)}
                              className={cn(
                                "flex h-9 items-center gap-2 rounded-md border px-3 text-sm transition-colors",
                                isCurrent
                                  ? "border-primary bg-primary text-primary-foreground"
                                  : "border-border bg-background/80 hover:bg-muted"
                              )}
                              disabled={isCurrent || publicationUpdating === updateKey}
                            >
                              {publicationUpdating === updateKey ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Icon className="h-4 w-4" />
                              )}
                              {option.label}
                            </button>
                          );
                        })}
                      </div>
                    {selectedImage.publication.quality_flags.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {selectedImage.publication.quality_flags.map((flag) => (
                          <span key={flag} className="rounded border border-border px-2 py-0.5 text-xs text-muted-foreground">
                            {flag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    {selectedExperimentRows.length > 0 && (
                      <div className="rounded-md border border-border bg-muted/30 p-3">
                        <div className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">Experiment</div>
                        <dl className="grid gap-2">
                          {selectedExperimentRows.map((row) => (
                            <div key={row.key} className="grid grid-cols-[120px_minmax(0,1fr)] gap-3 text-xs">
                              <dt className="capitalize text-muted-foreground">{row.label}</dt>
                              <dd className="break-words font-medium text-foreground">
                                {formatMetadataValue(row.value)}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      </div>
                    )}

                    {selectedMetadataRows.length > 0 && (
                      <div className="rounded-md border border-border bg-muted/30 p-3">
                        <div className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">Metadata</div>
                        <dl className="grid gap-2">
                          {selectedMetadataRows.map((row) => (
                            <div key={row.key} className="grid grid-cols-[120px_minmax(0,1fr)] gap-3 text-xs">
                              <dt className="capitalize text-muted-foreground">{row.label}</dt>
                              <dd className="break-words font-medium text-foreground">{row.value}</dd>
                            </div>
                          ))}
                        </dl>
                      </div>
                    )}
                  </div>
                </div>

                <div className="border-t border-border p-4">
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      onClick={(event) => handleCopyPrompt(selectedImage, event)}
                      className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-border bg-background text-sm transition hover:bg-muted"
                      disabled={!selectedImage.prompt.trim()}
                    >
                      {copiedPromptPath === selectedImage.catalog_path ? (
                        <Check className="h-4 w-4 text-emerald-500" />
                      ) : (
                        <Copy className="h-4 w-4" />
                      )}
                      {copiedPromptPath === selectedImage.catalog_path ? "Copied" : "Prompt"}
                    </button>
                    <button
                      onClick={(event) => handleOpenOriginal(selectedImage, event)}
                      className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-border bg-background text-sm transition hover:bg-muted"
                    >
                      <ExternalLink className="h-4 w-4" />
                      Open
                    </button>
                    <button
                      onClick={(event) => handleDownload(selectedImage.path, selectedImage.prompt, event)}
                      className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-primary text-sm text-primary-foreground transition hover:opacity-90"
                    >
                      <Download className="h-4 w-4" />
                      Download
                    </button>
                    <button
                      onClick={(event) => handleDelete(selectedImage.path, event)}
                      className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-destructive text-sm text-destructive-foreground transition hover:opacity-90"
                      disabled={deleting === selectedImage.path}
                    >
                      {deleting === selectedImage.path ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                      Delete
                    </button>
                  </div>
                </div>
              </aside>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
