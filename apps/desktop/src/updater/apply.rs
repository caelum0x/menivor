use std::process::{Command, Stdio};

use super::download::{verify_staged_update, StagedUpdate};

#[derive(Clone, Debug, Eq, PartialEq)]
struct InstallerCommand {
    program: String,
    args: Vec<String>,
}

pub(crate) fn launch_verified_installer(staged: &StagedUpdate) -> Result<(), String> {
    verify_staged_update(staged)?;
    let command = installer_command(staged, std::env::consts::OS)?;
    Command::new(&command.program)
        .args(&command.args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("Launch verified update installer: {error}"))?;
    Ok(())
}

fn installer_command(staged: &StagedUpdate, os: &str) -> Result<InstallerCommand, String> {
    let path = absolute_utf8_path(&staged.artifact_path)?;
    match (os, staged.kind.as_str()) {
        ("macos", "pkg") => Ok(InstallerCommand {
            program: "/usr/bin/open".into(),
            args: vec![path],
        }),
        ("windows", "msi") => Ok(InstallerCommand {
            program: "msiexec.exe".into(),
            args: vec!["/i".into(), path],
        }),
        ("linux", "appimage") => Ok(InstallerCommand {
            program: path,
            args: vec![],
        }),
        _ => Err(format!(
            "The staged {} artifact cannot install on {os}.",
            staged.kind
        )),
    }
}

fn absolute_utf8_path(path: &std::path::Path) -> Result<String, String> {
    if !path.is_absolute() {
        return Err("The staged update path must be absolute.".into());
    }
    path.to_str()
        .map(str::to_owned)
        .ok_or_else(|| "The staged update path is not valid UTF-8.".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn staged(kind: &str) -> StagedUpdate {
        StagedUpdate {
            version: "1.2.3".into(),
            channel: crate::updater::ReleaseChannel::Stable,
            platform: "test".into(),
            arch: "x86_64".into(),
            kind: kind.into(),
            artifact_path: PathBuf::from("/var/tmp/Menivor Update.pkg"),
            size_bytes: 1,
            sha256: "0".repeat(64),
            signed_manifest: b"signed manifest".to_vec(),
        }
    }

    #[test]
    fn builds_argument_safe_platform_installer_commands() {
        assert_eq!(
            installer_command(&staged("pkg"), "macos").unwrap(),
            InstallerCommand {
                program: "/usr/bin/open".into(),
                args: vec!["/var/tmp/Menivor Update.pkg".into()]
            }
        );
        assert_eq!(
            installer_command(&staged("msi"), "windows").unwrap(),
            InstallerCommand {
                program: "msiexec.exe".into(),
                args: vec!["/i".into(), "/var/tmp/Menivor Update.pkg".into()]
            }
        );
        assert_eq!(
            installer_command(&staged("appimage"), "linux")
                .unwrap()
                .program,
            "/var/tmp/Menivor Update.pkg"
        );
        assert!(installer_command(&staged("msi"), "linux").is_err());
    }

    #[test]
    fn relative_staged_paths_are_never_launched() {
        let mut relative = staged("pkg");
        relative.artifact_path = PathBuf::from("update.pkg");
        assert!(installer_command(&relative, "macos").is_err());
    }
}
