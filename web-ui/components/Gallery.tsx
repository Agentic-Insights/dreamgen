"use client";
/* eslint-disable @next/next/no-img-element */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Trash2, Download, X, Loader2, Clock, FileText,
  Calendar, Grid, ChevronRight, Folder, Star, Eye, EyeOff, Archive,
  UploadCloud
} from "lucide-react";
import {
  api,
  API_BASE,
  type GalleryCatalogEntry,
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
  const [syncStatus, setSyncStatus] = useState<GallerySyncStatus | null>(null);
  const loadRequestRef = useRef(0);

  const imagesPerPage = viewMode === "all" ? ALL_PAGE_SIZE : WEEK_PAGE_SIZE;

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
    const cacheKey = `gallery_catalog_${viewMode}_${catalogFilter}_${page}_${limit}`;

    setLoading(true);
    setError(null);

    try {
      console.log('Fetching gallery catalog from API');
      const [catalogResponse, publishStatus] = await Promise.all([
        api.getGalleryCatalog(limit, offset, catalogFilter, GALLERY_TIMEOUT_MS),
        api.getGallerySyncStatus(10),
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
  }, [catalogFilter, organizeByWeek, page, viewMode]);

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
  }, [catalogFilter, viewMode]);

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
    link.href = `${API_BASE}${imagePath}`;
    const filename = imagePath.split("/").pop() || "image.png";
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
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
            src={`${API_BASE}${image.path}`}
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
                              src={`${API_BASE}${img.path}`}
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

      {/* Modal for selected image */}
      {selectedImage && (
        <div
          className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setSelectedImage(null)}
        >
          <div
            className="relative max-w-6xl max-h-[90vh] bg-background rounded-lg overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="absolute top-0 left-0 right-0 bg-gradient-to-b from-background via-background/80 to-transparent p-4 z-10">
              <div className="flex items-start justify-between">
                <div className="flex-1 mr-4">
                  <p className="text-sm font-medium line-clamp-2">{selectedImage.prompt}</p>
                  <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {formatDate(selectedImage.created_at)}
                    </span>
                    <span>{formatSize(selectedImage.size)}</span>
                    {renderStateBadge(selectedImage.publication.state)}
                  </div>
                </div>
                <button
                  onClick={() => setSelectedImage(null)}
                  className="p-2 hover:bg-muted rounded-lg transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Modal Body - Image */}
            <div className="flex items-center justify-center">
              <img
                src={`${API_BASE}${selectedImage.path}`}
                alt={selectedImage.prompt}
                className="max-w-full max-h-[80vh] object-contain"
              />
            </div>

            {/* Modal Footer */}
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-background via-background/80 to-transparent p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                <div className="min-w-0">
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>Publish state</span>
                    {!selectedImage.publication.publishable && (
                      <span className="rounded border border-border px-2 py-0.5">not publishable</span>
                    )}
                    {selectedImage.publication.quality_flags.map((flag) => (
                      <span key={flag} className="rounded border border-border px-2 py-0.5">
                        {flag}
                      </span>
                    ))}
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
                            "flex h-9 items-center gap-2 rounded border border-border px-3 text-sm transition-colors",
                            isCurrent
                              ? "bg-primary text-primary-foreground"
                              : "bg-background/80 hover:bg-muted"
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
                </div>
                <div className="flex gap-2 justify-end">
                  <button
                    onClick={(e) => handleDownload(selectedImage.path, selectedImage.prompt, e)}
                    className="px-4 py-2 bg-primary text-primary-foreground rounded hover:opacity-90 flex items-center gap-2"
                  >
                    <Download className="w-4 h-4" />
                    Download
                  </button>
                  <button
                    onClick={(e) => {
                      handleDelete(selectedImage.path, e);
                    }}
                    className="px-4 py-2 bg-destructive text-destructive-foreground rounded hover:opacity-90 flex items-center gap-2"
                    disabled={deleting === selectedImage.path}
                  >
                    {deleting === selectedImage.path ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Trash2 className="w-4 h-4" />
                    )}
                    Delete
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
