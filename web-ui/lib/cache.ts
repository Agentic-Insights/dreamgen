// IndexedDB cache for gallery data with 24-hour TTL

interface CachedData<T = unknown> {
  data: T;
  timestamp: number;
  key: string;
}

class GalleryCache {
  private dbName = 'GalleryCache';
  private storeName = 'galleryData';
  private version = 2;
  private ttl = 24 * 60 * 60 * 1000; // 24 hours in milliseconds
  private db: IDBDatabase | null = null;

  async init(): Promise<void> {
    if (this.db) return;

    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, this.version);

      request.onerror = () => {
        console.error('Failed to open IndexedDB');
        reject(request.error);
      };

      request.onsuccess = () => {
        this.db = request.result;
        resolve();
      };

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;

        if (db.objectStoreNames.contains(this.storeName)) {
          db.deleteObjectStore(this.storeName);
        }

        const store = db.createObjectStore(this.storeName, { keyPath: 'key' });
        store.createIndex('timestamp', 'timestamp', { unique: false });
      };
    });
  }

  async get<T = unknown>(key: string): Promise<T | null> {
    await this.init();

    return new Promise((resolve) => {
      if (!this.db) {
        resolve(null);
        return;
      }

      const transaction = this.db.transaction([this.storeName], 'readonly');
      const store = transaction.objectStore(this.storeName);
      const request = store.get(key);

      request.onsuccess = () => {
        const result = request.result as CachedData<T> | undefined;

        if (!result) {
          resolve(null);
          return;
        }

        // Check if cache is expired
        const now = Date.now();
        if (now - result.timestamp > this.ttl) {
          // Cache expired, delete it
          this.delete(key);
          resolve(null);
          return;
        }

        resolve(result.data);
      };

      request.onerror = () => {
        console.error('Failed to get from cache:', request.error);
        resolve(null); // Return null on error rather than rejecting
      };
    });
  }

  async set<T = unknown>(key: string, data: T): Promise<void> {
    await this.init();

    return new Promise((resolve) => {
      if (!this.db) {
        resolve();
        return;
      }

      const transaction = this.db.transaction([this.storeName], 'readwrite');
      const store = transaction.objectStore(this.storeName);

      const cacheData: CachedData<T> = {
        key,
        data,
        timestamp: Date.now()
      };

      const request = store.put(cacheData);

      request.onsuccess = () => {
        resolve();
      };

      request.onerror = () => {
        console.error('Failed to set cache:', request.error);
        resolve(); // Don't fail if cache write fails
      };
    });
  }

  async delete(key: string): Promise<void> {
    await this.init();

    return new Promise((resolve) => {
      if (!this.db) {
        resolve();
        return;
      }

      const transaction = this.db.transaction([this.storeName], 'readwrite');
      const store = transaction.objectStore(this.storeName);
      const request = store.delete(key);

      request.onsuccess = () => {
        resolve();
      };

      request.onerror = () => {
        console.error('Failed to delete from cache:', request.error);
        resolve(); // Don't fail if cache delete fails
      };
    });
  }

  async clear(): Promise<void> {
    await this.init();

    return new Promise((resolve) => {
      if (!this.db) {
        resolve();
        return;
      }

      const transaction = this.db.transaction([this.storeName], 'readwrite');
      const store = transaction.objectStore(this.storeName);
      const request = store.clear();

      request.onsuccess = () => {
        resolve();
      };

      request.onerror = () => {
        console.error('Failed to clear cache:', request.error);
        resolve();
      };
    });
  }

  // Clean up expired entries
  async cleanup(): Promise<void> {
    await this.init();

    return new Promise((resolve) => {
      if (!this.db) {
        resolve();
        return;
      }

      const transaction = this.db.transaction([this.storeName], 'readwrite');
      const store = transaction.objectStore(this.storeName);
      const index = store.index('timestamp');
      const now = Date.now();
      const cutoff = now - this.ttl;

      const request = index.openCursor(IDBKeyRange.upperBound(cutoff));

      request.onsuccess = (event) => {
        const cursor = (event.target as IDBRequest).result;
        if (cursor) {
          store.delete(cursor.primaryKey);
          cursor.continue();
        } else {
          resolve();
        }
      };

      request.onerror = () => {
        console.error('Failed to cleanup cache:', request.error);
        resolve();
      };
    });
  }
}

// Singleton instance
const galleryCache = new GalleryCache();

// Initialize and cleanup on load
if (typeof window !== 'undefined') {
  galleryCache.init().then(() => {
    galleryCache.cleanup(); // Clean expired entries on startup
  }).catch(console.error);
}

export default galleryCache;
