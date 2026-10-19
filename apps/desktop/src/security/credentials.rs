//! Credential-store boundary. Deliberately has no filesystem implementation:
//! a desktop API key must live in the OS credential manager or not at all.

pub(crate) const SERVICE: &str = "reelforge-desktop";
const ACCOUNT: &str = "api-key";

pub(crate) trait CredentialStore: Send + Sync {
    fn save_api_key(&self, api_key: &str) -> Result<(), String>;
    fn load_api_key(&self) -> Result<Option<String>, String>;
    fn clear_api_key(&self) -> Result<(), String>;
}

/// Select the platform-native vault. There is intentionally no filesystem
/// implementation: if the OS facility is absent, saving a credential fails.
pub(crate) fn system_credential_store() -> Box<dyn CredentialStore> {
    #[cfg(target_os = "macos")]
    {
        Box::new(MacOsKeychainStore)
    }
    #[cfg(target_os = "windows")]
    {
        Box::new(WindowsCredentialStore)
    }
    #[cfg(target_os = "linux")]
    {
        Box::new(LinuxSecretServiceStore)
    }
    #[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
    {
        Box::new(UnavailableCredentialStore)
    }
}

/// Used until the platform keychain adapter is initialized. This explicit error
/// is safer than silently persisting a personal API key in preferences.
pub(crate) struct UnavailableCredentialStore;

impl CredentialStore for UnavailableCredentialStore {
    fn save_api_key(&self, _api_key: &str) -> Result<(), String> {
        Err(
            "The operating-system credential store is unavailable; the API key was not saved."
                .into(),
        )
    }
    fn load_api_key(&self) -> Result<Option<String>, String> {
        Err("The operating-system credential store is unavailable.".into())
    }
    fn clear_api_key(&self) -> Result<(), String> {
        Ok(())
    }
}

/// Native macOS Keychain implementation. The `security` utility writes only to
/// the login keychain; preferences never see the raw API key.
#[cfg(target_os = "macos")]
pub(crate) struct MacOsKeychainStore;

#[cfg(target_os = "macos")]
impl CredentialStore for MacOsKeychainStore {
    fn save_api_key(&self, api_key: &str) -> Result<(), String> {
        let output = std::process::Command::new("security")
            .args([
                "add-generic-password",
                "-U",
                "-s",
                SERVICE,
                "-a",
                ACCOUNT,
                "-w",
                api_key,
            ])
            .output()
            .map_err(|err| format!("Could not access macOS Keychain: {err}"))?;
        if output.status.success() {
            Ok(())
        } else {
            Err("macOS Keychain refused the API key; it was not saved.".into())
        }
    }

    fn load_api_key(&self) -> Result<Option<String>, String> {
        let output = std::process::Command::new("security")
            .args(["find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"])
            .output()
            .map_err(|err| format!("Could not access macOS Keychain: {err}"))?;
        if output.status.success() {
            Ok(Some(
                String::from_utf8_lossy(&output.stdout).trim().to_owned(),
            ))
        } else {
            // `security` does not distinguish a missing item portably; treating
            // it as absent keeps first-run settings quiet.
            Ok(None)
        }
    }

    fn clear_api_key(&self) -> Result<(), String> {
        let output = std::process::Command::new("security")
            .args(["delete-generic-password", "-s", SERVICE, "-a", ACCOUNT])
            .output()
            .map_err(|err| format!("Could not access macOS Keychain: {err}"))?;
        if output.status.success() {
            Ok(())
        } else {
            Ok(()) // already absent is the desired end state
        }
    }
}

/// Windows Credential Locker implementation. PasswordVault is backed by the
/// current user's Windows credential store. PowerShell receives the secret on
/// stdin, never through a preference file or command-line argument.
#[cfg(target_os = "windows")]
pub(crate) struct WindowsCredentialStore;

#[cfg(target_os = "windows")]
impl WindowsCredentialStore {
    fn run(script: &str, input: Option<&str>) -> Result<std::process::Output, String> {
        use std::io::Write;
        use std::process::{Command, Stdio};

        let mut command = Command::new("powershell.exe");
        command
            .args(["-NoProfile", "-NonInteractive", "-Command", script])
            .stdin(if input.is_some() {
                Stdio::piped()
            } else {
                Stdio::null()
            })
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let mut child = command
            .spawn()
            .map_err(|err| format!("Could not access Windows Credential Manager: {err}"))?;
        if let Some(secret) = input {
            child
                .stdin
                .take()
                .ok_or_else(|| "Could not open the credential-store input stream.".to_owned())?
                .write_all(secret.as_bytes())
                .map_err(|err| format!("Could not write to Windows Credential Manager: {err}"))?;
        }
        child
            .wait_with_output()
            .map_err(|err| format!("Could not read Windows Credential Manager: {err}"))
    }
}

#[cfg(target_os = "windows")]
impl CredentialStore for WindowsCredentialStore {
    fn save_api_key(&self, api_key: &str) -> Result<(), String> {
        let script = format!(
            "$v=[Windows.Security.Credentials.PasswordVault,Windows.Security.Credentials,ContentType=WindowsRuntime]::new(); try {{$v.Remove($v.Retrieve('{SERVICE}','{ACCOUNT}'))}} catch {{}}; $s=[Console]::In.ReadToEnd(); $v.Add([Windows.Security.Credentials.PasswordCredential]::new('{SERVICE}','{ACCOUNT}',$s))"
        );
        let output = Self::run(&script, Some(api_key))?;
        if output.status.success() {
            Ok(())
        } else {
            Err("Windows Credential Manager refused the API key; it was not saved.".into())
        }
    }

    fn load_api_key(&self) -> Result<Option<String>, String> {
        let script = format!(
            "$v=[Windows.Security.Credentials.PasswordVault,Windows.Security.Credentials,ContentType=WindowsRuntime]::new(); try {{$c=$v.Retrieve('{SERVICE}','{ACCOUNT}'); $c.RetrievePassword(); [Console]::Out.Write($c.Password)}} catch {{ exit 3 }}"
        );
        let output = Self::run(&script, None)?;
        if output.status.success() {
            Ok(Some(String::from_utf8_lossy(&output.stdout).to_string()))
        } else if output.status.code() == Some(3) {
            Ok(None)
        } else {
            Err("Windows Credential Manager is unavailable.".into())
        }
    }

    fn clear_api_key(&self) -> Result<(), String> {
        let script = format!(
            "$v=[Windows.Security.Credentials.PasswordVault,Windows.Security.Credentials,ContentType=WindowsRuntime]::new(); try {{$v.Remove($v.Retrieve('{SERVICE}','{ACCOUNT}'))}} catch {{}}"
        );
        let output = Self::run(&script, None)?;
        if output.status.success() {
            Ok(())
        } else {
            Err("Windows Credential Manager is unavailable.".into())
        }
    }
}

/// Linux Secret Service implementation via the freedesktop `secret-tool`
/// client. It talks to GNOME Keyring/KWallet through D-Bus; no plaintext
/// fallback is permitted when a desktop session has no Secret Service.
#[cfg(target_os = "linux")]
pub(crate) struct LinuxSecretServiceStore;

#[cfg(target_os = "linux")]
impl CredentialStore for LinuxSecretServiceStore {
    fn save_api_key(&self, api_key: &str) -> Result<(), String> {
        use std::io::Write;
        use std::process::{Command, Stdio};

        let mut child = Command::new("secret-tool")
            .args([
                "store",
                "--label=Menivor Desktop API key",
                "service",
                SERVICE,
                "account",
                ACCOUNT,
            ])
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|err| format!("Could not access Linux Secret Service: {err}"))?;
        child
            .stdin
            .take()
            .ok_or_else(|| "Could not open Secret Service input.".to_owned())?
            .write_all(api_key.as_bytes())
            .map_err(|err| format!("Could not write to Linux Secret Service: {err}"))?;
        if child
            .wait()
            .map_err(|err| format!("Could not read Linux Secret Service: {err}"))?
            .success()
        {
            Ok(())
        } else {
            Err("Linux Secret Service refused the API key; it was not saved.".into())
        }
    }

    fn load_api_key(&self) -> Result<Option<String>, String> {
        let output = std::process::Command::new("secret-tool")
            .args(["lookup", "service", SERVICE, "account", ACCOUNT])
            .output()
            .map_err(|err| format!("Could not access Linux Secret Service: {err}"))?;
        if output.status.success() {
            let value = String::from_utf8_lossy(&output.stdout).trim().to_owned();
            Ok((!value.is_empty()).then_some(value))
        } else {
            Ok(None)
        }
    }

    fn clear_api_key(&self) -> Result<(), String> {
        let output = std::process::Command::new("secret-tool")
            .args(["clear", "service", SERVICE, "account", ACCOUNT])
            .output()
            .map_err(|err| format!("Could not access Linux Secret Service: {err}"))?;
        if output.status.success() {
            Ok(())
        } else {
            Err("Linux Secret Service is unavailable.".into())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{CredentialStore, UnavailableCredentialStore, SERVICE};

    #[test]
    fn unavailable_store_never_accepts_a_secret() {
        assert_eq!(SERVICE, "reelforge-desktop");
        assert!(UnavailableCredentialStore.save_api_key("secret").is_err());
    }
}
