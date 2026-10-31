use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;
use tauri::{Manager, State};

static NEXT_REQUEST_ID: AtomicU64 = AtomicU64::new(1);

struct BridgeRequest {
    id: u64,
    method: String,
    params: Value,
    reply: mpsc::Sender<Result<Value, String>>,
}

struct BridgeState {
    requests: mpsc::SyncSender<BridgeRequest>,
    child: Arc<Mutex<Child>>,
}

#[tauri::command]
async fn bridge_call(
    state: State<'_, BridgeState>,
    method: String,
    params: Option<Value>,
) -> Result<Value, String> {
    let (reply, answer) = mpsc::channel();
    state.requests.try_send(BridgeRequest {
        id: NEXT_REQUEST_ID.fetch_add(1, Ordering::Relaxed),
        method,
        params: params.unwrap_or_else(|| json!({})),
        reply,
    }).map_err(|error| match error {
        mpsc::TrySendError::Full(_) => "Python 后端正忙，请稍后重试".to_string(),
        mpsc::TrySendError::Disconnected(_) => "Python 后端已停止".to_string(),
    })?;
    let child = Arc::clone(&state.child);
    tauri::async_runtime::spawn_blocking(move || {
        match answer.recv_timeout(Duration::from_secs(5)) {
            Ok(result) => result,
            Err(_) => {
                if let Ok(mut process) = child.lock() {
                    let _ = process.kill();
                    let _ = process.wait();
                }
                Err("Python 后端响应超时，进程已停止".to_string())
            }
        }
    }).await.map_err(|error| error.to_string())?
}

fn spawn_backend(app: &tauri::App) -> Result<BridgeState, String> {
    let mut command = if cfg!(debug_assertions) {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let python = std::env::var_os("RKA_PYTHON")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| {
                let venv = if cfg!(windows) {
                    root.join(".venv/Scripts/python.exe")
                } else {
                    root.join(".venv/bin/python")
                };
                if venv.exists() { venv } else {
                    std::path::PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
                }
            });
        let mut command = Command::new(python);
        command.arg("-m").arg("rka_desktop.desktop_bridge")
            .current_dir(&root).env("PYTHONPATH", root.join("src"));
        command
    } else {
        let name = if cfg!(windows) { "rka-backend.exe" } else { "rka-backend" };
        let path = app.path().resource_dir().map_err(|error| error.to_string())?.join(name);
        let data_dir = app.path().app_data_dir().map_err(|error| error.to_string())?;
        std::fs::create_dir_all(&data_dir).map_err(|error| error.to_string())?;
        let mut command = Command::new(path);
        command.env("DB_PATH", data_dir.join("rka.db"));
        command
    };
    let mut process = command.stdin(Stdio::piped()).stdout(Stdio::piped())
        .stderr(Stdio::piped()).spawn()
        .map_err(|error| format!("无法启动 Python 后端：{error}"))?;
    let mut stdin = process.stdin.take().ok_or("无法连接 Python 后端输入")?;
    let stdout = process.stdout.take().ok_or("无法连接 Python 后端输出")?;
    let stderr = process.stderr.take().ok_or("无法连接 Python 后端错误输出")?;
    let recent_error = Arc::new(Mutex::new(String::new()));
    let error_sink = Arc::clone(&recent_error);
    std::thread::spawn(move || {
        for line in BufReader::new(stderr).lines().map_while(Result::ok) {
            if let Ok(mut error) = error_sink.lock() {
                error.push_str(&line);
                error.push('\n');
                if error.len() > 4000 {
                    *error = error.chars().rev().take(4000).collect::<String>().chars().rev().collect();
                }
            }
        }
    });
    let child = Arc::new(Mutex::new(process));
    let (requests, receiver) = mpsc::sync_channel::<BridgeRequest>(1);
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        for request in receiver {
            let message = json!({"id": request.id, "method": request.method, "params": request.params});
            let response = (|| -> Result<Value, String> {
                writeln!(stdin, "{message}").map_err(|error| error.to_string())?;
                stdin.flush().map_err(|error| error.to_string())?;
                let mut line = String::new();
                if reader.read_line(&mut line).map_err(|error| error.to_string())? == 0 {
                    return Err("Python 后端已退出".to_string());
                }
                let reply: Value = serde_json::from_str(&line).map_err(|error| error.to_string())?;
                if reply["id"] != request.id { return Err("Python 后端响应编号不匹配".to_string()); }
                if reply["ok"] == true { Ok(reply["result"].clone()) } else {
                    Err(reply["error"]["message"].as_str()
                        .unwrap_or("Python 后端请求失败").to_string())
                }
            })();
            let response = response.map_err(|message| {
                let detail = recent_error.lock().ok().map(|value| value.clone()).unwrap_or_default();
                if detail.is_empty() { message } else { format!("{message}: {detail}") }
            });
            let _ = request.reply.send(response);
        }
    });
    Ok(BridgeState { requests, child })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let bridge = spawn_backend(app).map_err(std::io::Error::other)?;
            app.manage(bridge);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![bridge_call])
        .build(tauri::generate_context!())
        .expect("error while building RKA-3000 desktop application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Some(bridge) = app.try_state::<BridgeState>() {
                    if let Ok(mut child) = bridge.child.lock() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        });
}
