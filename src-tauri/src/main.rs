//! RKA-3000 desktop shell: window, Python sidecar lifecycle and an allow-listed IPC bridge.
//!
//! The shell never implements device protocols, calculations or data access. It starts the
//! Python backend, holds the per-launch bearer token, forwards allow-listed API calls over
//! loopback HTTP and shuts the backend down when the window exits.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    env,
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{mpsc, Arc, Mutex},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use rand::RngCore;
use reqwest::blocking::Client;
use serde::Serialize;
use serde_json::{json, Value};
use tauri::{Manager, RunEvent, State};

const EXPECTED_API_VERSION: u64 = 1;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(30);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(20);
const SHUTDOWN_GRACE: Duration = Duration::from_secs(90);
const TOKEN_ENV: &str = "RKA3000_API_TOKEN";
const SIDECAR_NAME: &str = if cfg!(windows) {
    "rka3000-backend.exe"
} else {
    "rka3000-backend"
};

#[derive(Clone)]
struct Connection {
    url: String,
    token: String,
    export_dir: Option<String>,
}

#[derive(Default)]
struct ExitInfo {
    exited: bool,
    code: Option<i32>,
}

struct Backend {
    child: Mutex<Option<Child>>,
    // Held for the whole app lifetime: when this process dies the OS closes the pipe and the
    // backend sees EOF on stdin, cancels the run and exits on its own.
    stdin: Mutex<Option<ChildStdin>>,
    connection: Result<Connection, String>,
    exit: Arc<Mutex<ExitInfo>>,
}

impl Backend {
    fn unavailable(error: String) -> Self {
        Backend {
            child: Mutex::new(None),
            stdin: Mutex::new(None),
            connection: Err(error),
            exit: Arc::new(Mutex::new(ExitInfo::default())),
        }
    }
}

#[derive(Serialize)]
struct BackendStatus {
    available: bool,
    exited: bool,
    exit_code: Option<i32>,
    error: Option<String>,
}

fn data_dir() -> Option<PathBuf> {
    if let Some(value) = env::var_os("RKA3000_DATA_DIR") {
        return Some(PathBuf::from(value));
    }
    if cfg!(windows) {
        env::var_os("LOCALAPPDATA").map(|base| PathBuf::from(base).join("RKA3000"))
    } else if cfg!(target_os = "macos") {
        env::var_os("HOME").map(|home| {
            PathBuf::from(home)
                .join("Library")
                .join("Application Support")
                .join("RKA3000")
        })
    } else {
        env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/share/rka3000"))
    }
}

/// Release builds have no console; startup diagnostics go to the user log directory.
fn desktop_log(message: &str) {
    eprintln!("{message}");
    let Some(directory) = data_dir().map(|root| root.join("logs")) else {
        return;
    };
    if fs::create_dir_all(&directory).is_err() {
        return;
    }
    if let Ok(mut file) = OpenOptions::new()
        .create(true)
        .append(true)
        .open(directory.join("desktop.log"))
    {
        let seconds = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|elapsed| elapsed.as_secs())
            .unwrap_or_default();
        let _ = writeln!(file, "unix={seconds} {message}");
    }
}

fn sidecar_path() -> Option<PathBuf> {
    let directory = env::current_exe().ok()?.parent()?.to_path_buf();
    let sidecar = directory.join(SIDECAR_NAME);
    sidecar.is_file().then_some(sidecar)
}

/// Release builds only run the frozen backend shipped next to the executable.
#[cfg(not(debug_assertions))]
fn backend_command() -> Result<(Command, PathBuf), String> {
    let sidecar = sidecar_path()
        .ok_or_else(|| format!("未找到随包业务服务 {SIDECAR_NAME}，请重新安装或完整解压便携包"))?;
    Ok((Command::new(&sidecar), sidecar))
}

/// Development builds use RKA3000_PYTHON, else the repository .venv, else a sidecar next to
/// the binary. There is no fallback to an arbitrary interpreter on PATH.
#[cfg(debug_assertions)]
fn backend_command() -> Result<(Command, PathBuf), String> {
    let python = if let Some(value) = env::var_os("RKA3000_PYTHON") {
        Some(PathBuf::from(value))
    } else {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_default();
        let local = root.join(if cfg!(windows) {
            ".venv/Scripts/python.exe"
        } else {
            ".venv/bin/python"
        });
        local.is_file().then_some(local)
    };
    if let Some(python) = python {
        let mut command = Command::new(&python);
        command.args(["-m", "rka_desktop.adapters.api"]);
        return Ok((command, python));
    }
    if let Some(sidecar) = sidecar_path() {
        return Ok((Command::new(&sidecar), sidecar));
    }
    Err("开发构建需要仓库 .venv 或 RKA3000_PYTHON 指向已安装 rka_desktop 的解释器".to_string())
}

fn new_token() -> String {
    let mut bytes = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut bytes);
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn start_backend() -> Result<Backend, String> {
    let token = new_token();
    let (mut command, executable) = backend_command()?;
    command
        .args(["--port", "0", "--exit-on-stdin-eof"])
        .env(TOKEN_ENV, &token)
        .env("PYTHONUTF8", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = command
        .spawn()
        .map_err(|e| format!("无法启动 Python 业务服务（{}）: {e}", executable.display()))?;
    let stdout = child.stdout.take().ok_or("Python 就绪管道不可用")?;
    let (sender, receiver) = mpsc::channel();
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        let result = reader
            .read_line(&mut line)
            .map_err(|e| e.to_string())
            .and_then(|read| {
                if read == 0 {
                    Err("业务服务在报告端口前退出".to_string())
                } else {
                    serde_json::from_str::<Value>(&line).map_err(|e| format!("握手格式无效: {e}"))
                }
            });
        let _ = sender.send(result);
        // Keep draining so the backend never blocks on a full stdout pipe.
        let mut sink = String::new();
        while reader.read_line(&mut sink).map(|n| n > 0).unwrap_or(false) {
            sink.clear();
        }
    });
    let ready = receiver
        .recv_timeout(STARTUP_TIMEOUT)
        .map_err(|_| "等待 Python 业务服务就绪超时".to_string())
        .and_then(|value| value)
        .and_then(|value| {
            let api_version = value["api_version"].as_u64().unwrap_or(0);
            if api_version != EXPECTED_API_VERSION {
                return Err(format!(
                    "业务服务接口版本 {api_version} 与桌面程序要求的 {EXPECTED_API_VERSION} 不匹配"
                ));
            }
            value["port"]
                .as_u64()
                .filter(|port| *port > 0 && *port <= u16::MAX as u64)
                .ok_or_else(|| "Python 返回的监听端口无效".to_string())
        });
    match ready {
        Ok(port) => {
            let mut connection = Connection {
                url: format!("http://127.0.0.1:{port}"),
                token,
                export_dir: None,
            };
            if let Ok(health) = request(&connection, "GET", "/api/health", None) {
                connection.export_dir = health["export_dir"].as_str().map(str::to_string);
            }
            let exit = Arc::new(Mutex::new(ExitInfo::default()));
            let backend = Backend {
                stdin: Mutex::new(child.stdin.take()),
                child: Mutex::new(Some(child)),
                connection: Ok(connection),
                exit,
            };
            Ok(backend)
        }
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            Err(format!(
                "{error}；请确认 {SIDECAR_NAME} 与桌面程序位于同一目录"
            ))
        }
    }
}

/// Polls the child so the page can distinguish "backend crashed" from a transient error.
fn watch_backend(backend: &Backend) {
    let exit = backend.exit.clone();
    let Ok(guard) = backend.child.lock() else {
        return;
    };
    let Some(child) = guard.as_ref() else {
        return;
    };
    let pid = child.id();
    drop(guard);
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_millis(500));
        // try_wait needs &mut Child; probe liveness through the process table instead.
        if !process_alive(pid) {
            if let Ok(mut info) = exit.lock() {
                if !info.exited {
                    info.exited = true;
                    desktop_log("业务服务进程已退出（非桌面请求）");
                }
            }
            return;
        }
    });
}

#[cfg(unix)]
fn process_alive(pid: u32) -> bool {
    extern "C" {
        fn kill(pid: i32, sig: i32) -> i32;
    }
    unsafe { kill(pid as i32, 0) == 0 }
}

#[cfg(windows)]
fn process_alive(pid: u32) -> bool {
    use std::ffi::c_void;
    #[link(name = "kernel32")]
    extern "system" {
        fn OpenProcess(access: u32, inherit: i32, pid: u32) -> *mut c_void;
        fn GetExitCodeProcess(handle: *mut c_void, code: *mut u32) -> i32;
        fn CloseHandle(handle: *mut c_void) -> i32;
    }
    const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
    const STILL_ACTIVE: u32 = 259;
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            return false;
        }
        let mut code: u32 = 0;
        let ok = GetExitCodeProcess(handle, &mut code);
        CloseHandle(handle);
        ok != 0 && code == STILL_ACTIVE
    }
}

fn request(
    connection: &Connection,
    method: &str,
    path: &str,
    body: Option<Value>,
) -> Result<Value, String> {
    let client = Client::builder()
        .no_proxy()
        .timeout(REQUEST_TIMEOUT)
        .build()
        .map_err(|e| e.to_string())?;
    let method = method
        .parse::<reqwest::Method>()
        .map_err(|e| e.to_string())?;
    let mut builder = client
        .request(method, format!("{}{path}", connection.url))
        .bearer_auth(&connection.token);
    if let Some(body) = body {
        builder = builder.json(&body);
    }
    let response = builder.send().map_err(|e| {
        json!({"code": "unreachable", "message": format!("本地业务服务不可用: {e}")}).to_string()
    })?;
    let status = response.status();
    let payload: Value = response
        .json()
        .map_err(|e| json!({"code": "bad_response", "message": e.to_string()}).to_string())?;
    if !status.is_success() {
        let error = payload
            .get("error")
            .cloned()
            .unwrap_or_else(|| json!({"code": "http_error", "message": format!("HTTP {status}")}));
        return Err(error.to_string());
    }
    Ok(payload)
}

fn is_numeric(segment: &str) -> bool {
    !segment.is_empty() && segment.len() <= 12 && segment.bytes().all(|b| b.is_ascii_digit())
}

fn is_task_id(segment: &str) -> bool {
    segment.len() == 32 && segment.bytes().all(|b| b.is_ascii_hexdigit())
}

/// Only these method/path shapes reach the backend; shutdown is deliberately absent.
fn allowed(method: &str, path: &str) -> bool {
    let path = path.split('?').next().unwrap_or("");
    let segments: Vec<&str> = path.trim_matches('/').split('/').collect();
    match (method, segments.as_slice()) {
        (
            "GET",
            ["api", "health" | "settings" | "recipes" | "run" | "devices" | "experiments" | "alarms"
            | "audit" | "tasks" | "log"],
        ) => true,
        ("PUT", ["api", "settings"]) => true,
        ("POST", ["api", "recipes"]) | ("POST", ["api", "recipes", "import"]) => true,
        ("GET" | "PUT" | "DELETE", ["api", "recipes", id]) => is_numeric(id),
        ("GET", ["api", "recipes", id, "export"]) => is_numeric(id),
        ("GET", ["api", "run", "measurements"]) => true,
        (
            "POST",
            ["api", "run", "start" | "pause" | "resume" | "stop" | "ack-alarm" | "reset-interlock" | "gas-mode"
            | "manual-gas"],
        ) => true,
        ("GET", ["api", "devices", "status"]) => true,
        ("POST", ["api", "devices", "connect" | "mfc" | "temperature" | "tare"]) => true,
        ("GET" | "PATCH" | "DELETE", ["api", "experiments", id]) => is_numeric(id),
        ("GET", ["api", "experiments", id, "measurements"]) => is_numeric(id),
        ("GET" | "PUT", ["api", "experiments", id, "sample-params"]) => is_numeric(id),
        ("POST", ["api", "experiments", id, "kinetics" | "report" | "export"]) => is_numeric(id),
        ("GET", ["api", "tasks", id]) => is_task_id(id),
        ("POST", ["api", "tasks", id, "cancel"]) => is_task_id(id),
        _ => false,
    }
}

#[tauri::command]
async fn api_request(
    backend: State<'_, Backend>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<Value, String> {
    if !allowed(&method, &path) {
        return Err(json!({"code": "forbidden", "message": "不支持的业务接口"}).to_string());
    }
    if backend.exit.lock().map(|info| info.exited).unwrap_or(false) {
        return Err(
            json!({"code": "backend_exited", "message": "业务服务已退出，请重新启动程序"})
                .to_string(),
        );
    }
    let connection = backend
        .connection
        .clone()
        .map_err(|e| json!({"code": "backend_unavailable", "message": e}).to_string())?;
    tauri::async_runtime::spawn_blocking(move || request(&connection, &method, &path, body))
        .await
        .map_err(|e| json!({"code": "internal", "message": e.to_string()}).to_string())?
}

#[tauri::command]
fn backend_status(backend: State<'_, Backend>) -> BackendStatus {
    let info = backend.exit.lock().ok();
    BackendStatus {
        available: backend.connection.is_ok(),
        exited: info.as_ref().map(|i| i.exited).unwrap_or(false),
        exit_code: info.as_ref().and_then(|i| i.code),
        error: backend.connection.as_ref().err().cloned(),
    }
}

/// Opens the folder containing an export produced by the backend. The path must live inside
/// the export directory reported by the backend; nothing else can be opened.
#[tauri::command]
fn reveal_export(backend: State<'_, Backend>, path: String) -> Result<(), String> {
    let connection = backend.connection.clone()?;
    let export_dir = connection.export_dir.ok_or("业务服务没有报告导出目录")?;
    let export_root = fs::canonicalize(&export_dir).map_err(|e| e.to_string())?;
    let target = fs::canonicalize(&path).map_err(|_| "导出文件不存在".to_string())?;
    if !target.starts_with(&export_root) {
        return Err("只能打开导出目录中的文件".to_string());
    }
    let mut command = if cfg!(windows) {
        let mut c = Command::new("explorer");
        c.arg(format!("/select,{}", target.display()));
        c
    } else if cfg!(target_os = "macos") {
        let mut c = Command::new("open");
        c.arg("-R").arg(&target);
        c
    } else {
        let mut c = Command::new("xdg-open");
        c.arg(target.parent().unwrap_or(&export_root));
        c
    };
    command.spawn().map(|_| ()).map_err(|e| e.to_string())
}

fn stop_backend(backend: &Backend) {
    let Ok(connection) = &backend.connection else {
        return;
    };
    let Ok(mut guard) = backend.child.lock() else {
        return;
    };
    let Some(mut child) = guard.take() else {
        return;
    };
    // Python stops the run, waits for measurement flush / device release, then exits.
    let _ = request(connection, "POST", "/api/shutdown", None);
    if let Ok(mut stdin) = backend.stdin.lock() {
        stdin.take(); // fallback signal if the HTTP request did not get through
    }
    let deadline = Instant::now() + SHUTDOWN_GRACE;
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                if let Ok(mut info) = backend.exit.lock() {
                    info.exited = true;
                    info.code = status.code();
                }
                break;
            }
            _ if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(50)),
            _ => {
                desktop_log("业务服务未在 90 秒内完成清理，强制结束");
                let _ = child.kill();
                let _ = child.wait();
                break;
            }
        }
    }
}

#[cfg(windows)]
fn show_error(message: &str) {
    use std::{ffi::c_void, iter::once, ptr::null_mut};
    #[link(name = "user32")]
    extern "system" {
        fn MessageBoxW(hwnd: *mut c_void, text: *const u16, caption: *const u16, kind: u32) -> i32;
    }
    let text: Vec<u16> = message.encode_utf16().chain(once(0)).collect();
    let caption: Vec<u16> = "RKA-3000 实验系统".encode_utf16().chain(once(0)).collect();
    unsafe {
        MessageBoxW(null_mut(), text.as_ptr(), caption.as_ptr(), 0x10); // MB_OK | MB_ICONERROR
    }
}

#[cfg(not(windows))]
fn show_error(_message: &str) {}

fn fatal(message: &str) -> ! {
    desktop_log(message);
    show_error(message);
    std::process::exit(1);
}

fn main() {
    let app = tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            api_request,
            backend_status,
            reveal_export
        ])
        .setup(|app| {
            // Keep the window usable so the page can explain why the backend is unavailable.
            let backend = start_backend().unwrap_or_else(|error| {
                desktop_log(&format!("业务服务启动失败: {error}"));
                Backend::unavailable(format!("本地业务服务启动失败：{error}"))
            });
            watch_backend(&backend);
            app.manage(backend);
            Ok(())
        })
        .build(tauri::generate_context!())
        .unwrap_or_else(|error| {
            fatal(&format!(
                "无法创建桌面窗口：{error}\n请确认已安装 Microsoft Edge WebView2 Runtime。"
            ))
        });
    app.run(|app, event| {
        if matches!(event, RunEvent::Exit) {
            stop_backend(&app.state::<Backend>());
        }
    });
}
