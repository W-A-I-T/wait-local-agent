use std::{
    error::Error,
    fs::{self, OpenOptions},
    io::{ErrorKind, Read, Write},
    net::{TcpStream, ToSocketAddrs},
    path::{Path, PathBuf},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};

use tauri::{Manager, WindowEvent};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};
use tauri_plugin_updater::UpdaterExt;

const API_HOST: &str = "127.0.0.1";
const API_PORT: u16 = 8788;
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const TOKEN_STORAGE_KEY: &str = "wait-local-agent-api-token";
const UPDATE_CHECK_TIMEOUT: Duration = Duration::from_secs(15);

#[derive(Default)]
struct SidecarState {
    child: Mutex<Option<CommandChild>>,
}

struct RuntimeConfig {
    data_path: PathBuf,
    vault_path: PathBuf,
    admin_token: String,
}

fn main() {
    tauri::Builder::default()
        .manage(SidecarState::default())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let window = app.get_webview_window("main").ok_or_else(|| {
                std::io::Error::other("main window is missing from the Tauri configuration")
            })?;
            window.hide()?;

            let app_data_dir = app.path().app_data_dir()?;
            let runtime = RuntimeConfig::load(&app_data_dir)?;

            // The existing dashboard reads its token from localStorage. Seed it
            // before the hidden window is made visible so the API remains
            // authenticated without changing the product screens.
            window.eval(&format!(
                "window.localStorage.setItem('{}', '{}');",
                TOKEN_STORAGE_KEY, runtime.admin_token
            ))?;

            let (receiver, child) = app
                .shell()
                .sidecar("wait-local-agent-server")?
                .env("WAIT_HOST", API_HOST)
                .env("WAIT_PORT", API_PORT.to_string())
                .env("WAIT_DATA_PATH", &runtime.data_path)
                .env("WAIT_VAULT_PATH", &runtime.vault_path)
                .env("WAIT_ADMIN_TOKEN", &runtime.admin_token)
                .env("WAIT_DEMO_MODE", "false")
                .spawn()?;

            app.state::<SidecarState>()
                .child
                .lock()
                .map_err(|_| std::io::Error::other("sidecar state lock poisoned"))?
                .replace(child);

            tauri::async_runtime::spawn(async move {
                let mut receiver = receiver;
                while let Some(event) = receiver.recv().await {
                    match event {
                        CommandEvent::Stderr(line) => {
                            eprintln!(
                                "wait-local-agent-server: {}",
                                String::from_utf8_lossy(&line)
                            );
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("wait-local-agent-server exited: {:?}", payload.code);
                            break;
                        }
                        _ => {}
                    }
                }
            });

            let updater_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(error) = check_for_updates(updater_handle).await {
                    eprintln!("WAIT Local Agent updater check skipped: {error}");
                }
            });

            let handle = app.handle().clone();
            let token = runtime.admin_token;
            thread::spawn(move || {
                let ready = wait_for_health(&token);
                let ui_handle = handle.clone();
                let _ = handle.run_on_main_thread(move || match ready {
                    Ok(()) => {
                        if let Some(window) = ui_handle.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    Err(error) => {
                        stop_sidecar(&ui_handle);
                        ui_handle
                            .dialog()
                            .message(format!(
                                "WAIT Local Agent could not start its local workspace. {error}"
                            ))
                            .kind(MessageDialogKind::Error)
                            .title("WAIT Local Agent")
                            .show(|_| {});
                    }
                });
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, WindowEvent::CloseRequested { .. }) {
                stop_sidecar(window.app_handle());
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running WAIT Local Agent");
}

async fn check_for_updates<R: tauri::Runtime>(
    app: tauri::AppHandle<R>,
) -> tauri_plugin_updater::Result<()> {
    let update = app
        .updater_builder()
        .timeout(UPDATE_CHECK_TIMEOUT)
        .build()?
        .check()
        .await?;

    let Some(update) = update else {
        eprintln!("WAIT Local Agent updater: no update available");
        return Ok(());
    };

    let should_install = app
        .dialog()
        .message(format!(
            "WAIT Local Agent {} is available. Install it now?",
            update.version
        ))
        .title("WAIT Local Agent update")
        .buttons(MessageDialogButtons::YesNo)
        .kind(MessageDialogKind::Info)
        .blocking_show();

    if !should_install {
        eprintln!("WAIT Local Agent updater: update declined");
        return Ok(());
    }

    update
        .download_and_install(
            |chunk_length, content_length| {
                eprintln!(
                    "WAIT Local Agent updater: downloaded {chunk_length} bytes (total: {content_length:?})"
                );
            },
            || eprintln!("WAIT Local Agent updater: download finished"),
        )
        .await?;

    eprintln!("WAIT Local Agent updater: update installed; restarting");
    app.restart();
}

impl RuntimeConfig {
    fn load(app_data_dir: &Path) -> Result<Self, Box<dyn Error>> {
        let vault_path = app_data_dir.join("vault");
        let data_path = app_data_dir.join("state.db");
        fs::create_dir_all(&vault_path)?;
        fs::create_dir_all(app_data_dir)?;

        let token_path = app_data_dir.join("admin-token");
        let admin_token = match fs::read_to_string(&token_path) {
            Ok(token) if !token.trim().is_empty() => token.trim().to_owned(),
            _ => create_admin_token(&token_path)?,
        };

        Ok(Self {
            data_path,
            vault_path,
            admin_token,
        })
    }
}

fn create_admin_token(path: &Path) -> Result<String, Box<dyn Error>> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes)?;
    let token: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();

    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(path)?;
    file.write_all(token.as_bytes())?;
    file.write_all(b"\n")?;
    file.flush()?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    }

    Ok(token)
}

fn wait_for_health(token: &str) -> Result<(), Box<dyn Error + Send + Sync>> {
    let address = (API_HOST, API_PORT)
        .to_socket_addrs()?
        .next()
        .ok_or_else(|| std::io::Error::other("loopback health address did not resolve"))?;
    let deadline = Instant::now() + HEALTH_TIMEOUT;
    let request = format!(
        "GET /health HTTP/1.1\r\nHost: {API_HOST}:{API_PORT}\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n"
    );

    loop {
        if Instant::now() >= deadline {
            return Err(std::io::Error::new(
                ErrorKind::TimedOut,
                "the local workspace did not become ready within 30 seconds",
            )
            .into());
        }

        if let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(500)) {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            if stream.write_all(request.as_bytes()).is_ok() {
                let mut response = Vec::new();
                if stream.read_to_end(&mut response).is_ok()
                    && response.starts_with(b"HTTP/1.1 200")
                {
                    return Ok(());
                }
            }
        }
        thread::sleep(Duration::from_millis(250));
    }
}

fn stop_sidecar<R: tauri::Runtime>(handle: &tauri::AppHandle<R>) {
    if let Some(child) = handle
        .state::<SidecarState>()
        .child
        .lock()
        .ok()
        .and_then(|mut child| child.take())
    {
        let _ = child.kill();
    }
}
