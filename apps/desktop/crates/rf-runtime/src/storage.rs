use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

const MAX_SNAPSHOT_BYTES: u64 = 16 * 1024 * 1024;
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

/// Opaque persistence boundary for desktop-local job state.
///
/// The runtime owns the snapshot schema. Implementations only need to load the
/// last complete byte sequence and atomically replace it with a new one.
pub trait JobStorage: Send + Sync {
    fn load(&self) -> Result<Option<Vec<u8>>, StorageError>;
    /// Atomically replace the prior snapshot. Implementations must return an
    /// error only while the prior snapshot is still the visible value.
    fn replace(&self, snapshot: &[u8]) -> Result<(), StorageError>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StorageError {
    Io(String),
    Corrupt(String),
}

impl fmt::Display for StorageError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StorageError::Io(message) => write!(f, "job storage I/O failed: {message}"),
            StorageError::Corrupt(message) => write!(f, "job snapshot is corrupt: {message}"),
        }
    }
}

impl std::error::Error for StorageError {}

/// One-file local store. Replacement is temp/write/fsync/rename and, on Unix,
/// the containing directory is fsynced as well so the rename survives restart.
#[derive(Debug, Clone)]
pub struct LocalAtomicJobStorage {
    path: PathBuf,
}

impl LocalAtomicJobStorage {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    fn parent(&self) -> &Path {
        self.path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."))
    }

    fn reject_symlink_destination(&self) -> Result<(), StorageError> {
        match fs::symlink_metadata(&self.path) {
            Ok(metadata) if metadata.file_type().is_symlink() => Err(StorageError::Io(format!(
                "refusing symlink job-store destination {}",
                self.path.display()
            ))),
            Ok(_) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(StorageError::Io(format!(
                "inspect {}: {error}",
                self.path.display()
            ))),
        }
    }
}

impl JobStorage for LocalAtomicJobStorage {
    fn load(&self) -> Result<Option<Vec<u8>>, StorageError> {
        self.reject_symlink_destination()?;
        let mut file = match File::open(&self.path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => {
                return Err(StorageError::Io(format!(
                    "open {}: {error}",
                    self.path.display()
                )))
            }
        };
        let length = file
            .metadata()
            .map_err(|error| StorageError::Io(format!("stat {}: {error}", self.path.display())))?
            .len();
        if length > MAX_SNAPSHOT_BYTES {
            return Err(StorageError::Corrupt(format!(
                "{} is {length} bytes (limit {MAX_SNAPSHOT_BYTES})",
                self.path.display()
            )));
        }
        let mut bytes = Vec::with_capacity(length as usize);
        file.read_to_end(&mut bytes)
            .map_err(|error| StorageError::Io(format!("read {}: {error}", self.path.display())))?;
        Ok(Some(bytes))
    }

    fn replace(&self, snapshot: &[u8]) -> Result<(), StorageError> {
        if snapshot.len() as u64 > MAX_SNAPSHOT_BYTES {
            return Err(StorageError::Io(format!(
                "snapshot is {} bytes (limit {MAX_SNAPSHOT_BYTES})",
                snapshot.len()
            )));
        }
        let parent = self.parent();
        fs::create_dir_all(parent).map_err(|error| {
            StorageError::Io(format!("create directory {}: {error}", parent.display()))
        })?;
        self.reject_symlink_destination()?;

        let file_name = self
            .path
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or_else(|| StorageError::Io("job-store filename is not valid UTF-8".into()))?;
        let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let temp_path = parent.join(format!(
            ".{file_name}.{}.{}.tmp",
            std::process::id(),
            sequence
        ));

        let write_result = (|| -> Result<(), StorageError> {
            let mut temp = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&temp_path)
                .map_err(|error| {
                    StorageError::Io(format!("create {}: {error}", temp_path.display()))
                })?;
            temp.write_all(snapshot).map_err(|error| {
                StorageError::Io(format!("write {}: {error}", temp_path.display()))
            })?;
            temp.flush().map_err(|error| {
                StorageError::Io(format!("flush {}: {error}", temp_path.display()))
            })?;
            temp.sync_all().map_err(|error| {
                StorageError::Io(format!("fsync {}: {error}", temp_path.display()))
            })?;
            drop(temp);

            // On Unix this atomically replaces an existing regular file. The
            // symlink check above prevents following a pre-existing destination.
            fs::rename(&temp_path, &self.path).map_err(|error| {
                StorageError::Io(format!(
                    "rename {} to {}: {error}",
                    temp_path.display(),
                    self.path.display()
                ))
            })?;

            // The new file is already the visible committed value after rename,
            // so a directory-fsync failure cannot be reported as a failed
            // replacement without making the caller roll back to a false view.
            // It remains a best-effort crash-durability hardening step.
            #[cfg(unix)]
            let _ = File::open(parent).and_then(|directory| directory.sync_all());
            Ok(())
        })();

        if write_result.is_err() {
            let _ = fs::remove_file(&temp_path);
        }
        write_result
    }
}
