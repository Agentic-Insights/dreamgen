"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import {
  Trash2, Download, X, Loader2, Clock, FileText, ZoomIn,
  Calendar, Grid, ChevronDown, ChevronRight, Folder
} from "lucide-react";
import { api, getImageUrl } from "@/lib/api";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import galleryCache from "@/lib/cache";

interface GalleryImage {
  path: string;
  prompt: string;
  created_at: string;
  size: number;
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

export default function Gallery() {
  const [images, setImages] = useState<GalleryImage[]>([]);
  const [weekGroups, setWeekGroups] = useState<WeekGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedImage, setSelectedImage] = useState<GalleryImage | null>(null);
  const [expandedWeeks, setExpandedWeeks] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("week");

  const imagesPerPage = viewMode === "all" ? 20 : 200; // Load reasonable amount for week view

  const loadImages = async () => {
    setLoading(true);
    setError(null);

    try {
      // Create cache key based on view mode and page
      const cacheKey = `gallery_${viewMode}_${page}_${viewMode === "all" ? imagesPerPage : 200}`;

      // Try to get from cache first
      const cachedData = await galleryCache.get<GalleryResponse>(cacheKey);

      if (cachedData) {
        console.log('Loading gallery from cache');
        setImages(cachedData.images);
        setTotal(cachedData.total);

        if (viewMode === "week") {
          organizeByWeek(cachedData.images);
        }
        setLoading(false);
        return;
      }

      // If not in cache or expired, fetch from API
      console.log('Fetching gallery from API');
      const response: GalleryResponse = await api.getGallery(
        viewMode === "all" ? imagesPerPage : 200, // Load reasonable amount for week view
        viewMode === "all" ? page * imagesPerPage : 0
      );

      // Save to cache
      await galleryCache.set(cacheKey, {
        images: response.images,
        total: response.total
      });

      setImages(response.images);
      setTotal(response.total);

      if (viewMode === "week") {
        organizeByWeek(response.images);
      }
    } catch (err) {
      setError("Failed to load gallery");
      console.error('Gallery load error:', err);

      // Try to load from cache even if API fails
      try {
        const cacheKey = `gallery_${viewMode}_${page}_${viewMode === "all" ? imagesPerPage : 200}`;
        const cachedData = await galleryCache.get<GalleryResponse>(cacheKey);

        if (cachedData) {
          console.log('API failed, using cached data');
          setImages(cachedData.images);
          setTotal(cachedData.total);

          if (viewMode === "week") {
            organizeByWeek(cachedData.images);
          }
          setError(null); // Clear error if cache loads successfully
        }
      } catch (cacheErr) {
        console.error('Cache fallback failed:', cacheErr);
      }
    } finally {
      setLoading(false);
    }
  };

  const organizeByWeek = (images: GalleryImage[]) => {
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
  };

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
    loadImages();
  }, [page, viewMode]);

  const handleDelete = async (imagePath: string, event: React.MouseEvent) => {
    event.stopPropagation();
    if (!confirm("Are you sure you want to delete this image?")) return;

    setDeleting(imagePath);
    try {
      const pathParts = imagePath.split("/images/");
      const relativePath = pathParts[1] || imagePath;
      await api.deleteImage(relativePath);

      // Clear cache after deletion
      await galleryCache.clear();

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
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

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
                >
                  <Download className="w-3.5 h-3.5" />
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
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">Gallery</h2>
              <p className="text-sm text-muted-foreground">{total} images generated</p>
            </div>
            <div className="flex items-center gap-2">
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
                  await galleryCache.clear(); // Clear cache on manual refresh
                  loadImages();
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
                src={getImageUrl(selectedImage.path)}
                alt={selectedImage.prompt}
                className="max-w-full max-h-[80vh] object-contain"
              />
            </div>

            {/* Modal Footer */}
            <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-background via-background/80 to-transparent p-4">
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
      )}
    </>
  );
}
