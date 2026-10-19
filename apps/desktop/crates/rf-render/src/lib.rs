//! Local render-farm coordinator (`rf-render`). A machine + its LAN peers form a
//! $0-wallet render pool: the coordinator hands pending render tasks to available
//! nodes as time-boxed **leases**, reclaims expired leases (a crashed node's task
//! goes back to the queue), and stops assigning once every node is at capacity.
//! Pure scheduling logic — `now`/task-source are injected — so it is deterministic
//! and unit-testable; the transport to nodes lives in the GUI/runtime layer.

use rf_jobs::RenderJob;
use std::collections::{HashMap, HashSet};
use std::fmt;

#[derive(Debug, Clone)]
pub struct Node {
    pub id: String,
    pub capacity: u32, // max concurrent leases (e.g. GPU count)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Lease {
    pub task_id: String,
    pub node_id: String,
    pub expires_at: u64, // monotonic seconds
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RestoreLeaseError {
    Expired { task_id: String },
    UnknownNode { task_id: String, node_id: String },
    DuplicateTask { task_id: String },
    NodeAtCapacity { node_id: String },
}

impl fmt::Display for RestoreLeaseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RestoreLeaseError::Expired { task_id } => {
                write!(f, "cannot restore expired lease for {task_id}")
            }
            RestoreLeaseError::UnknownNode { task_id, node_id } => {
                write!(
                    f,
                    "cannot restore {task_id}: node {node_id} is not registered"
                )
            }
            RestoreLeaseError::DuplicateTask { task_id } => {
                write!(f, "task {task_id} already has a live lease")
            }
            RestoreLeaseError::NodeAtCapacity { node_id } => {
                write!(f, "cannot restore lease: node {node_id} is at capacity")
            }
        }
    }
}

impl std::error::Error for RestoreLeaseError {}

#[derive(Debug, Default)]
pub struct Coordinator {
    nodes: Vec<Node>,
    leases: Vec<Lease>,
    lease_ttl_s: u64,
}

impl Coordinator {
    pub fn new(lease_ttl_s: u64) -> Self {
        Coordinator {
            nodes: Vec::new(),
            leases: Vec::new(),
            lease_ttl_s,
        }
    }

    pub fn add_node(&mut self, id: &str, capacity: u32) {
        self.nodes.push(Node {
            id: id.to_string(),
            capacity,
        });
    }

    pub fn has_node(&self, id: &str) -> bool {
        self.nodes.iter().any(|node| node.id == id)
    }

    fn active_leases(&self, now: u64) -> impl Iterator<Item = &Lease> {
        self.leases.iter().filter(move |l| l.expires_at > now)
    }

    /// Import leases recovered from durable storage onto their exact prior
    /// nodes. Validation is atomic: either every lease is admitted or none are.
    pub fn restore_leases(
        &mut self,
        recovered: &[Lease],
        now: u64,
    ) -> Result<(), RestoreLeaseError> {
        let mut tasks: HashSet<String> = self
            .active_leases(now)
            .map(|lease| lease.task_id.clone())
            .collect();
        let mut load = self.load_per_node(now);
        for lease in recovered {
            if lease.expires_at <= now {
                return Err(RestoreLeaseError::Expired {
                    task_id: lease.task_id.clone(),
                });
            }
            if !tasks.insert(lease.task_id.clone()) {
                return Err(RestoreLeaseError::DuplicateTask {
                    task_id: lease.task_id.clone(),
                });
            }
            let Some(node) = self.nodes.iter().find(|node| node.id == lease.node_id) else {
                return Err(RestoreLeaseError::UnknownNode {
                    task_id: lease.task_id.clone(),
                    node_id: lease.node_id.clone(),
                });
            };
            let used = load.entry(node.id.clone()).or_insert(0);
            if *used >= node.capacity {
                return Err(RestoreLeaseError::NodeAtCapacity {
                    node_id: node.id.clone(),
                });
            }
            *used += 1;
        }
        self.leases.extend_from_slice(recovered);
        Ok(())
    }

    pub fn has_active_lease(&self, task_id: &str, now: u64) -> bool {
        self.active_leases(now)
            .any(|lease| lease.task_id == task_id)
    }

    pub fn lease_for(&self, task_id: &str, now: u64) -> Option<&Lease> {
        self.active_leases(now)
            .find(|lease| lease.task_id == task_id)
    }

    /// Reclaim expired leases (crashed/stalled nodes); returns the freed task ids
    /// so the caller can requeue them.
    pub fn reclaim_expired(&mut self, now: u64) -> Vec<String> {
        let (expired, live): (Vec<Lease>, Vec<Lease>) =
            self.leases.drain(..).partition(|l| l.expires_at <= now);
        self.leases = live;
        expired.into_iter().map(|l| l.task_id).collect()
    }

    /// Heartbeat: a node still working on `task_id` pushes its lease deadline out
    /// by another TTL, so a render that legitimately runs longer than one lease
    /// window is not reclaimed and double-assigned. Returns `false` when there is
    /// no active lease for the task (already expired/reclaimed, or unknown).
    pub fn renew_lease(&mut self, task_id: &str, now: u64) -> bool {
        let ttl = self.lease_ttl_s;
        for lease in self.leases.iter_mut() {
            if lease.task_id == task_id && lease.expires_at > now {
                lease.expires_at = now + ttl;
                return true;
            }
        }
        false
    }

    /// A node reported the task finished: drop its lease so the slot frees
    /// immediately (rather than waiting for the TTL to expire). Returns `true`
    /// if a lease was removed.
    pub fn complete_task(&mut self, task_id: &str) -> bool {
        let before = self.leases.len();
        self.leases.retain(|l| l.task_id != task_id);
        self.leases.len() != before
    }

    fn load_per_node(&self, now: u64) -> HashMap<String, u32> {
        let mut load: HashMap<String, u32> = HashMap::new();
        for l in self.active_leases(now) {
            *load.entry(l.node_id.clone()).or_insert(0) += 1;
        }
        load
    }

    /// Assign as many pending tasks as capacity allows; returns the new leases.
    /// Nodes are filled in declared order; a task with no free node is left pending.
    ///
    /// A task that already holds an active lease is skipped (never double-assigned
    /// to a second node), and duplicate ids within one `pending` batch are
    /// collapsed — so a crashed-then-requeued task can't be rendered twice while
    /// its original lease is still live.
    pub fn assign(&mut self, pending: &[String], now: u64) -> Vec<Lease> {
        let mut load = self.load_per_node(now);
        let mut new_leases = Vec::new();
        // Seed the skip-set with already-leased task ids; `insert` returning false
        // filters both those and in-batch duplicates in a single pass.
        let mut seen: HashSet<String> =
            self.active_leases(now).map(|l| l.task_id.clone()).collect();
        let mut queue = pending.iter().filter(move |t| seen.insert((*t).clone()));
        'nodes: for node in &self.nodes {
            let used = load.get(&node.id).copied().unwrap_or(0);
            for _ in used..node.capacity {
                match queue.next() {
                    Some(task_id) => {
                        let lease = Lease {
                            task_id: task_id.clone(),
                            node_id: node.id.clone(),
                            expires_at: now + self.lease_ttl_s,
                        };
                        *load.entry(node.id.clone()).or_insert(0) += 1;
                        new_leases.push(lease.clone());
                        self.leases.push(lease);
                    }
                    None => break 'nodes, // no more pending tasks
                }
            }
        }
        new_leases
    }

    /// Job-driven scheduling: hand leases only to jobs that are still schedulable
    /// (non-terminal). A job already `Completed`/`Failed`/`Cancelled` — finished
    /// on another node, crashed, or aborted by the user — is never given a lease,
    /// so the pool never wastes a slot on work that is already done. Ordering of
    /// `jobs` is preserved (declared priority).
    pub fn assign_jobs(&mut self, jobs: &[RenderJob], now: u64) -> Vec<Lease> {
        let pending: Vec<String> = jobs
            .iter()
            .filter(|j| !j.state.is_terminal())
            .map(|j| j.id.clone())
            .collect();
        self.assign(&pending, now)
    }

    pub fn active_count(&self, now: u64) -> usize {
        self.active_leases(now).count()
    }

    pub fn total_capacity(&self) -> u32 {
        self.nodes.iter().map(|n| n.capacity).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn assigns_up_to_capacity() {
        let mut c = Coordinator::new(60);
        c.add_node("gpu-a", 2);
        c.add_node("gpu-b", 1);
        let leases = c.assign(&["t1".into(), "t2".into(), "t3".into(), "t4".into()], 100);
        // total capacity 3 -> only 3 assigned, t4 stays pending.
        assert_eq!(leases.len(), 3);
        assert_eq!(c.active_count(100), 3);
    }

    #[test]
    fn respects_existing_load() {
        let mut c = Coordinator::new(60);
        c.add_node("gpu-a", 2);
        c.assign(&["t1".into()], 100); // 1/2 used on gpu-a
        let more = c.assign(&["t2".into(), "t3".into()], 100);
        // only 1 free slot remains -> 1 assigned.
        assert_eq!(more.len(), 1);
        assert_eq!(c.active_count(100), 2);
    }

    #[test]
    fn reclaims_expired_leases() {
        let mut c = Coordinator::new(60);
        c.add_node("gpu-a", 1);
        c.assign(&["t1".into()], 100); // expires at 160
                                       // At t=200 the lease is expired and reclaimed.
        let freed = c.reclaim_expired(200);
        assert_eq!(freed, vec!["t1".to_string()]);
        assert_eq!(c.active_count(200), 0);
        // The freed slot can now take a new task.
        assert_eq!(c.assign(&["t2".into()], 200).len(), 1);
    }

    #[test]
    fn restores_a_live_lease_on_its_exact_node() {
        let mut c = Coordinator::new(60);
        c.add_node("gpu-a", 1);
        c.add_node("gpu-b", 1);
        c.restore_leases(
            &[Lease {
                task_id: "recovered".into(),
                node_id: "gpu-a".into(),
                expires_at: 160,
            }],
            120,
        )
        .unwrap();

        let next = c.assign(&["new".into()], 120);
        assert_eq!(next.len(), 1);
        assert_eq!(next[0].node_id, "gpu-b");
        assert_eq!(c.lease_for("recovered", 120).unwrap().node_id, "gpu-a");
    }

    #[test]
    fn lease_restore_validation_is_atomic() {
        let mut c = Coordinator::new(60);
        c.add_node("gpu-a", 1);
        let error = c
            .restore_leases(
                &[
                    Lease {
                        task_id: "valid".into(),
                        node_id: "gpu-a".into(),
                        expires_at: 160,
                    },
                    Lease {
                        task_id: "overflow".into(),
                        node_id: "gpu-a".into(),
                        expires_at: 160,
                    },
                ],
                120,
            )
            .unwrap_err();
        assert_eq!(
            error,
            RestoreLeaseError::NodeAtCapacity {
                node_id: "gpu-a".into()
            }
        );
        assert_eq!(c.active_count(120), 0);
    }

    #[test]
    fn total_capacity_sums_nodes() {
        let mut c = Coordinator::new(60);
        c.add_node("a", 2);
        c.add_node("b", 3);
        assert_eq!(c.total_capacity(), 5);
    }

    #[test]
    fn does_not_reassign_an_already_leased_task() {
        let mut c = Coordinator::new(60);
        c.add_node("gpu-a", 2);
        c.assign(&["t1".into()], 100); // t1 leased on gpu-a (1/2 used)
                                       // Requeuing t1 while its lease is live must NOT create a second lease.
        let again = c.assign(&["t1".into()], 100);
        assert!(again.is_empty());
        assert_eq!(c.active_count(100), 1);
    }

    #[test]
    fn dedupes_duplicate_ids_within_one_batch() {
        let mut c = Coordinator::new(60);
        c.add_node("gpu-a", 4);
        let leases = c.assign(&["t1".into(), "t1".into(), "t2".into()], 100);
        // t1 appears twice but is leased once.
        assert_eq!(leases.len(), 2);
        assert_eq!(c.active_count(100), 2);
    }

    #[test]
    fn renew_extends_a_live_lease() {
        let mut c = Coordinator::new(60);
        c.add_node("gpu-a", 1);
        c.assign(&["t1".into()], 100); // expires at 160
                                       // At t=150 the node heartbeats -> new deadline 210.
        assert!(c.renew_lease("t1", 150));
        // At t=200 the lease would have expired (160) but the renewal keeps it live.
        assert_eq!(c.reclaim_expired(200), Vec::<String>::new());
        assert_eq!(c.active_count(200), 1);
    }

    #[test]
    fn renew_fails_for_expired_or_unknown_task() {
        let mut c = Coordinator::new(60);
        c.add_node("gpu-a", 1);
        c.assign(&["t1".into()], 100); // expires at 160
        assert!(!c.renew_lease("t1", 200)); // already past expiry
        assert!(!c.renew_lease("ghost", 100)); // never leased
    }

    #[test]
    fn assign_jobs_skips_terminal_jobs() {
        use rf_jobs::{RenderJob, State};
        let mut c = Coordinator::new(60);
        c.add_node("gpu-a", 4);
        let mut done = RenderJob::new("t-done");
        done.complete(vec![]).unwrap();
        let mut cancelled = RenderJob::new("t-cancel");
        cancelled.cancel().unwrap();
        let queued = RenderJob::new("t-queued");
        let mut running = RenderJob::new("t-running");
        running.transition(State::InProgress, Some(0.3)).unwrap();

        let leases = c.assign_jobs(&[done, cancelled, queued, running], 100);
        // Only the queued + running jobs are schedulable.
        assert_eq!(leases.len(), 2);
        let ids: Vec<&str> = leases.iter().map(|l| l.task_id.as_str()).collect();
        assert!(ids.contains(&"t-queued") && ids.contains(&"t-running"));
        assert!(!ids.contains(&"t-done") && !ids.contains(&"t-cancel"));
    }

    #[test]
    fn complete_frees_the_slot_immediately() {
        let mut c = Coordinator::new(60);
        c.add_node("gpu-a", 1);
        c.assign(&["t1".into()], 100);
        assert_eq!(c.active_count(100), 1);
        assert!(c.complete_task("t1"));
        // Slot is free before the TTL — a new task can take it right away.
        assert_eq!(c.active_count(100), 0);
        assert_eq!(c.assign(&["t2".into()], 100).len(), 1);
        // Completing an unknown task is a no-op.
        assert!(!c.complete_task("ghost"));
    }
}
