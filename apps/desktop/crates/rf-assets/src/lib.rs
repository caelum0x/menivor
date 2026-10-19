//! Content-addressed asset store (`rf-assets`) for the desktop app. Assets
//! (gameplay B-roll, generated clips, images, audio) are keyed by a content hash
//! so identical bytes are stored once and shared across projects. This crate owns
//! the CAS *index* + dedup policy; the byte I/O (writing blobs to the on-disk
//! store) is the injectable boundary (a trait), so the index logic is
//! unit-testable. The demo hash is FNV-1a (stable, dependency-free); production
//! swaps in sha256 behind the same `cas_key` shape.

use std::collections::HashMap;

/// Compute the content-address key for a blob (FNV-1a 64-bit, hex).
pub fn cas_key(bytes: &[u8]) -> String {
    let mut hash: u64 = 0xcbf29ce484222325;
    for &b in bytes {
        hash ^= b as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{hash:016x}")
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AssetEntry {
    pub cas_key: String,
    pub kind: String, // clip | image | audio
    pub size: usize,
    pub refcount: u32,
}

/// The injectable byte-I/O boundary. The [`CasIndex`] owns the dedup *policy*; a
/// `BlobStore` persists/removes the actual bytes. Swappable — an on-disk store in
/// production, an in-memory one in tests — so the index logic stays unit-testable.
pub trait BlobStore {
    /// Persist `bytes` under `key`. Content-addressed, so writing an existing key
    /// is a no-op (an identical key means identical bytes).
    fn write(&mut self, key: &str, bytes: &[u8]);
    /// Remove the blob for `key` — called when its last reference drops.
    fn delete(&mut self, key: &str);
    /// True if a blob already exists for `key`.
    fn has(&self, key: &str) -> bool;
}

/// In-memory CAS index. `put` is idempotent by content: re-adding identical bytes
/// bumps the refcount instead of duplicating. `remove` decrements + reclaims at 0.
#[derive(Debug, Default)]
pub struct CasIndex {
    entries: HashMap<String, AssetEntry>,
    dedup_hits: u64,
}

impl CasIndex {
    pub fn new() -> Self {
        CasIndex::default()
    }

    /// Add bytes; returns the CAS key. Identical content dedupes (refcount++).
    pub fn put(&mut self, bytes: &[u8], kind: &str) -> String {
        let key = cas_key(bytes);
        match self.entries.get_mut(&key) {
            Some(entry) => {
                entry.refcount += 1;
                self.dedup_hits += 1;
            }
            None => {
                self.entries.insert(
                    key.clone(),
                    AssetEntry {
                        cas_key: key.clone(),
                        kind: kind.to_string(),
                        size: bytes.len(),
                        refcount: 1,
                    },
                );
            }
        }
        key
    }

    /// Add bytes, persisting them through `store` on the first occurrence only.
    /// A dedup hit bumps the refcount but performs no byte I/O (the blob already
    /// exists). Returns the CAS key. This is the doc's index-owns-policy /
    /// store-owns-bytes boundary.
    pub fn put_with<S: BlobStore>(&mut self, store: &mut S, bytes: &[u8], kind: &str) -> String {
        let key = self.put(bytes, kind);
        if !store.has(&key) {
            store.write(&key, bytes);
        }
        key
    }

    /// Decrement a ref through `store`; when the last ref drops, the blob is
    /// deleted from the store as well as the index. Returns true if reclaimed.
    pub fn remove_with<S: BlobStore>(&mut self, store: &mut S, key: &str) -> bool {
        let reclaimed = self.remove(key);
        if reclaimed {
            store.delete(key);
        }
        reclaimed
    }

    pub fn get(&self, key: &str) -> Option<&AssetEntry> {
        self.entries.get(key)
    }

    /// True if a blob for `key` is currently indexed.
    pub fn contains(&self, key: &str) -> bool {
        self.entries.contains_key(key)
    }

    /// Decrement a ref; the blob is reclaimed (removed) when the last ref drops.
    /// Returns true if the blob was reclaimed.
    pub fn remove(&mut self, key: &str) -> bool {
        if let Some(entry) = self.entries.get_mut(key) {
            if entry.refcount <= 1 {
                self.entries.remove(key);
                return true;
            }
            entry.refcount -= 1;
        }
        false
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// How many `put`s were satisfied by an existing blob (storage saved).
    pub fn dedup_hits(&self) -> u64 {
        self.dedup_hits
    }

    /// Total logical bytes stored once (dedup-aware).
    pub fn physical_bytes(&self) -> usize {
        self.entries.values().map(|e| e.size).sum()
    }

    /// Bytes that *would* be occupied without dedup — every reference counted
    /// (`Σ size × refcount`).
    pub fn logical_bytes(&self) -> usize {
        self.entries
            .values()
            .map(|e| e.size * e.refcount as usize)
            .sum()
    }

    /// Storage saved by dedup, in bytes (`logical − physical`). What the UI shows
    /// as "you saved X via deduplication".
    pub fn bytes_saved(&self) -> usize {
        self.logical_bytes() - self.physical_bytes()
    }

    /// Total asset references across all projects (`Σ refcount`).
    pub fn total_refs(&self) -> u64 {
        self.entries.values().map(|e| e.refcount as u64).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identical_content_dedupes() {
        let mut idx = CasIndex::new();
        let a = idx.put(b"gameplay-frames", "clip");
        let b = idx.put(b"gameplay-frames", "clip");
        assert_eq!(a, b);
        assert_eq!(idx.len(), 1);
        assert_eq!(idx.get(&a).unwrap().refcount, 2);
        assert_eq!(idx.dedup_hits(), 1);
    }

    #[test]
    fn distinct_content_distinct_keys() {
        let mut idx = CasIndex::new();
        let a = idx.put(b"one", "clip");
        let b = idx.put(b"two", "clip");
        assert_ne!(a, b);
        assert_eq!(idx.len(), 2);
    }

    #[test]
    fn refcount_reclaims_on_last_remove() {
        let mut idx = CasIndex::new();
        let k = idx.put(b"x", "image");
        idx.put(b"x", "image"); // refcount 2
        assert!(!idx.remove(&k)); // still referenced
        assert!(idx.remove(&k)); // last ref -> reclaimed
        assert!(idx.is_empty());
    }

    #[test]
    fn physical_bytes_counts_each_blob_once() {
        let mut idx = CasIndex::new();
        idx.put(b"aaaa", "clip");
        idx.put(b"aaaa", "clip"); // dedup, no extra bytes
        idx.put(b"bb", "clip");
        assert_eq!(idx.physical_bytes(), 6); // 4 + 2
    }

    #[test]
    fn savings_metrics_track_dedup() {
        let mut idx = CasIndex::new();
        idx.put(b"aaaa", "clip"); // 4 bytes
        idx.put(b"aaaa", "clip"); // dedup: logical +4, physical +0
        idx.put(b"bb", "clip"); // 2 bytes
        assert_eq!(idx.physical_bytes(), 6); // 4 + 2 stored once
        assert_eq!(idx.logical_bytes(), 10); // 4*2 + 2*1
        assert_eq!(idx.bytes_saved(), 4); // the deduped copy of "aaaa"
        assert_eq!(idx.total_refs(), 3);
    }

    /// Minimal in-memory `BlobStore` for exercising the index↔store boundary.
    #[derive(Default)]
    struct MemStore {
        blobs: HashMap<String, Vec<u8>>,
        writes: u32,
        deletes: u32,
    }
    impl BlobStore for MemStore {
        fn write(&mut self, key: &str, bytes: &[u8]) {
            self.blobs.insert(key.to_string(), bytes.to_vec());
            self.writes += 1;
        }
        fn delete(&mut self, key: &str) {
            self.blobs.remove(key);
            self.deletes += 1;
        }
        fn has(&self, key: &str) -> bool {
            self.blobs.contains_key(key)
        }
    }

    #[test]
    fn put_with_writes_bytes_once_across_dedup() {
        let mut idx = CasIndex::new();
        let mut store = MemStore::default();
        let k = idx.put_with(&mut store, b"gameplay", "clip");
        idx.put_with(&mut store, b"gameplay", "clip"); // dedup — no second write
        assert_eq!(store.writes, 1);
        assert!(store.has(&k));
        assert!(idx.contains(&k));
        assert_eq!(idx.get(&k).unwrap().refcount, 2);
    }

    #[test]
    fn remove_with_deletes_blob_on_last_ref_only() {
        let mut idx = CasIndex::new();
        let mut store = MemStore::default();
        let k = idx.put_with(&mut store, b"x", "image");
        idx.put_with(&mut store, b"x", "image"); // refcount 2, still 1 write
        assert!(!idx.remove_with(&mut store, &k)); // decrement only
        assert_eq!(store.deletes, 0);
        assert!(store.has(&k)); // bytes still present
        assert!(idx.remove_with(&mut store, &k)); // last ref -> delete
        assert_eq!(store.deletes, 1);
        assert!(!store.has(&k));
        assert!(idx.is_empty());
    }
}
