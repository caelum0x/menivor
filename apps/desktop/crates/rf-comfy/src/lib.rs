//! Local ComfyUI + Wan 2.2 bridge (`rf-comfy`). Runs a local/LAN ComfyUI as a
//! first-class routed provider. This crate owns the **VRAM-budgeted warm pool**:
//! which model checkpoints to keep resident given a GPU's VRAM, evicting the
//! least-recently-used to make room for a requested model. Pure policy (the actual
//! load/unload is the runtime's job) so it is deterministic + unit-testable.

use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct Model {
    pub name: String,
    pub vram_mb: u32,
}

#[derive(Debug)]
pub struct WarmPool {
    budget_mb: u32,
    /// resident model name -> last-used tick
    resident: HashMap<String, u64>,
    vram: HashMap<String, u32>,
    tick: u64,
    evictions: u64,
}

#[derive(Debug, PartialEq, Eq)]
pub enum Admit {
    /// Already resident (a warm hit) — no load needed.
    Warm,
    /// Loaded now; these models were evicted to make room.
    Loaded { evicted: Vec<String> },
    /// The model alone exceeds the VRAM budget — cannot run locally.
    TooLarge,
}

impl WarmPool {
    pub fn new(budget_mb: u32) -> Self {
        WarmPool {
            budget_mb,
            resident: HashMap::new(),
            vram: HashMap::new(),
            tick: 0,
            evictions: 0,
        }
    }

    /// VRAM currently held by resident models, in MB.
    pub fn used_mb(&self) -> u32 {
        self.resident
            .keys()
            .map(|k| self.vram.get(k).copied().unwrap_or(0))
            .sum()
    }

    /// Free VRAM headroom against the budget, in MB.
    pub fn free_mb(&self) -> u32 {
        self.budget_mb.saturating_sub(self.used_mb())
    }

    /// Would `model` fit right now *without* evicting anything? A resident model
    /// trivially fits. Lets the runtime prefer a local route only when it won't
    /// thrash the warm pool. Pure — never mutates.
    pub fn fits_without_eviction(&self, model: &Model) -> bool {
        model.vram_mb <= self.budget_mb
            && (self.resident.contains_key(&model.name) || model.vram_mb <= self.free_mb())
    }

    /// Request a model: keep it warm if resident, else load it, evicting LRU
    /// models until it fits (or report it's too large for the budget).
    pub fn request(&mut self, model: &Model) -> Admit {
        self.tick += 1;
        if model.vram_mb > self.budget_mb {
            return Admit::TooLarge;
        }
        if self.resident.contains_key(&model.name) {
            self.resident.insert(model.name.clone(), self.tick);
            return Admit::Warm;
        }
        // Evict LRU until the new model fits.
        let mut evicted = Vec::new();
        while self.used_mb() + model.vram_mb > self.budget_mb {
            let lru = self
                .resident
                .iter()
                .min_by_key(|(_, &t)| t)
                .map(|(k, _)| k.clone());
            match lru {
                Some(name) => {
                    self.resident.remove(&name);
                    // Drop the size entry too, or `vram` grows unboundedly with
                    // every distinct model ever loaded (a slow memory leak).
                    self.vram.remove(&name);
                    self.evictions += 1;
                    evicted.push(name);
                }
                None => break,
            }
        }
        self.vram.insert(model.name.clone(), model.vram_mb);
        self.resident.insert(model.name.clone(), self.tick);
        Admit::Loaded { evicted }
    }

    /// Explicitly unload a model (e.g. the user switched workflows), freeing its
    /// VRAM immediately rather than waiting for it to become the LRU eviction
    /// target. Returns `true` if it was resident.
    pub fn release(&mut self, name: &str) -> bool {
        let was = self.resident.remove(name).is_some();
        self.vram.remove(name);
        was
    }

    pub fn is_resident(&self, name: &str) -> bool {
        self.resident.contains_key(name)
    }

    pub fn resident_count(&self) -> usize {
        self.resident.len()
    }

    pub fn evictions(&self) -> u64 {
        self.evictions
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn m(name: &str, vram: u32) -> Model {
        Model {
            name: name.to_string(),
            vram_mb: vram,
        }
    }

    #[test]
    fn warm_hit_needs_no_reload() {
        let mut pool = WarmPool::new(24_000);
        assert!(matches!(
            pool.request(&m("wan22", 12_000)),
            Admit::Loaded { .. }
        ));
        assert_eq!(pool.request(&m("wan22", 12_000)), Admit::Warm);
        assert_eq!(pool.resident_count(), 1);
    }

    #[test]
    fn evicts_lru_to_fit() {
        let mut pool = WarmPool::new(24_000);
        pool.request(&m("a", 10_000)); // tick 1
        pool.request(&m("b", 10_000)); // tick 2 (used 20k)
                                       // 'c' needs 10k -> only 4k free -> evict LRU 'a'.
        let admit = pool.request(&m("c", 10_000));
        match admit {
            Admit::Loaded { evicted } => assert_eq!(evicted, vec!["a".to_string()]),
            other => panic!("expected Loaded, got {other:?}"),
        }
        assert!(!pool.is_resident("a") && pool.is_resident("b") && pool.is_resident("c"));
        assert_eq!(pool.evictions(), 1);
    }

    #[test]
    fn lru_respects_recent_use() {
        let mut pool = WarmPool::new(24_000);
        pool.request(&m("a", 10_000)); // tick 1
        pool.request(&m("b", 10_000)); // tick 2
        pool.request(&m("a", 10_000)); // tick 3 -> 'a' now MRU
                                       // Loading 'c' should evict 'b' (now LRU), not 'a'.
        if let Admit::Loaded { evicted } = pool.request(&m("c", 10_000)) {
            assert_eq!(evicted, vec!["b".to_string()]);
        } else {
            panic!("expected Loaded");
        }
    }

    #[test]
    fn model_larger_than_budget_is_rejected() {
        let mut pool = WarmPool::new(8_000);
        assert_eq!(pool.request(&m("huge", 16_000)), Admit::TooLarge);
    }

    #[test]
    fn tracks_used_and_free_vram() {
        let mut pool = WarmPool::new(24_000);
        assert_eq!(pool.free_mb(), 24_000);
        pool.request(&m("a", 10_000));
        assert_eq!(pool.used_mb(), 10_000);
        assert_eq!(pool.free_mb(), 14_000);
    }

    #[test]
    fn fits_without_eviction_reflects_headroom() {
        let mut pool = WarmPool::new(24_000);
        pool.request(&m("a", 10_000)); // 14k free
        assert!(pool.fits_without_eviction(&m("b", 14_000))); // exactly fits
        assert!(!pool.fits_without_eviction(&m("c", 15_000))); // would need eviction
        assert!(pool.fits_without_eviction(&m("a", 10_000))); // resident always fits
        assert!(!pool.fits_without_eviction(&m("huge", 30_000))); // over budget entirely
    }

    #[test]
    fn release_frees_vram_immediately() {
        let mut pool = WarmPool::new(24_000);
        pool.request(&m("a", 10_000));
        assert!(pool.release("a"));
        assert!(!pool.is_resident("a"));
        assert_eq!(pool.free_mb(), 24_000);
        // Releasing something not resident is a no-op.
        assert!(!pool.release("ghost"));
    }

    #[test]
    fn eviction_does_not_leak_size_entries() {
        // Cycle many distinct models through a small budget; `used_mb` must stay
        // bounded to the single resident model (no stale sizes inflating it).
        let mut pool = WarmPool::new(10_000);
        for i in 0..50 {
            pool.request(&m(&format!("model-{i}"), 10_000));
        }
        assert_eq!(pool.resident_count(), 1);
        assert_eq!(pool.used_mb(), 10_000);
        assert_eq!(pool.free_mb(), 0);
    }
}
