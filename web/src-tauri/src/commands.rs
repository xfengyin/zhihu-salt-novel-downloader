//! Tauri 命令模块
//!
//! 前端通过 `invoke` 调用 Rust 端命令，实现桌面端特有能力
//!
//! 内置命令：
//! - start_backend / stop_backend / get_backend_status: 管理后端服务
//! - open_download_dir: 打开下载目录
//! - get_app_version / get_platform_info: 应用元信息

use std::path::PathBuf;
use std::sync::Arc;
use std::process::{Child, Command, Stdio};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};
use tauri_plugin_shell::ShellExt;

use crate::backend::BackendManager;
use crate::error::{AppError, AppResult};

/// 后端状态
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackendStatus {
    pub running: bool,
    pub pid: Option<u32>,
    pub port: Option<u16>,
    pub host: Option<String>,
}

/// 应用信息
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppInfo {
    pub version: String,
    pub platform: String,
    pub arch: String,
    pub tauri_version: String,
}

/// 启动后端 FastAPI 服务
///
/// 策略：
/// - 桌面端打包时附带 Python 后端二进制（PyInstaller）
/// - 通过 spawn 启动后端子进程
/// - 返回进程 PID 和监听端口
#[tauri::command]
pub async fn start_backend(app: AppHandle) -> AppResult<BackendStatus> {
    log::info!("启动后端服务");

    let mut backend = BackendManager::new();

    // 查找后端可执行文件
    let backend_path = find_backend_binary(&app)?;
    log::info!("后端路径: {:?}", backend_path);

    let port = 38080;
    let host = "127.0.0.1";

    let child: Child = Command::new(&backend_path)
        .args([
            "--host", host,
            "--port", &port.to_string(),
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| AppError::Backend(format!("启动后端失败: {}", e)))?;

    let pid = child.id();
    let status = BackendStatus {
        running: true,
        pid: Some(pid),
        port: Some(port),
        host: Some(host.to_string()),
    };

    // 注册到全局状态
    let manager = Arc::new(backend.with_child(child));
    app.manage(manager);

    log::info!("后端已启动: pid={}, port={}", pid, port);
    Ok(status)
}

/// 停止后端服务
#[tauri::command]
pub async fn stop_backend(app: AppHandle) -> AppResult<()> {
    log::info!("停止后端服务");

    if let Some(manager) = app.try_state::<Arc<BackendManager>>() {
        manager.stop().map_err(|e| AppError::Backend(e.to_string()))?;
    }

    Ok(())
}

/// 获取后端状态
#[tauri::command]
pub async fn get_backend_status(app: AppHandle) -> AppResult<BackendStatus> {
    if let Some(manager) = app.try_state::<Arc<BackendManager>>() {
        Ok(manager.status())
    } else {
        Ok(BackendStatus {
            running: false,
            pid: None,
            port: None,
            host: None,
        })
    }
}

/// 打开下载目录
#[tauri::command]
pub async fn open_download_dir(app: AppHandle, path: String) -> AppResult<()> {
    let path_buf = PathBuf::from(&path);
    let path = if path_buf.is_absolute() {
        path_buf
    } else {
        app.path().download_dir()?.join(&path_buf)
    };

    log::info!("打开目录: {:?}", path);

    // 确保目录存在
    if !path.exists() {
        std::fs::create_dir_all(&path)
            .map_err(|e| AppError::Io(format!("创建目录失败: {}", e)))?;
    }

    let shell = app.shell();
    shell.open(path.to_string_lossy().to_string(), None)
        .map_err(|e| AppError::Shell(e.to_string()))?;

    Ok(())
}

/// 获取应用版本
#[tauri::command]
pub fn get_app_version(app: AppHandle) -> AppResult<String> {
    Ok(app.package_info().version.to_string())
}

/// 获取平台信息
#[tauri::command]
pub fn get_platform_info() -> AppResult<AppInfo> {
    Ok(AppInfo {
        version: env!("CARGO_PKG_VERSION").to_string(),
        platform: std::env::consts::OS.to_string(),
        arch: std::env::consts::ARCH.to_string(),
        tauri_version: tauri::VERSION.to_string(),
    })
}

/// 查找后端二进制文件
fn find_backend_binary(app: &AppHandle) -> AppResult<PathBuf> {
    // 1. 资源目录（打包后）
    if let Ok(resource_dir) = app.path().resource_dir() {
        let bin_name = if cfg!(windows) { "zhihu-backend.exe" } else { "zhihu-backend" };
        let path = resource_dir.join("bin").join(bin_name);
        if path.exists() {
            return Ok(path);
        }
    }

    // 2. 同级目录（开发模式）
    if let Ok(exe_dir) = std::env::current_exe() {
        if let Some(parent) = exe_dir.parent() {
            let bin_name = if cfg!(windows) { "zhihu-backend.exe" } else { "zhihu-backend" };
            let path = parent.join("bin").join(bin_name);
            if path.exists() {
                return Ok(path);
            }
            // 直接同级
            let path = parent.join(bin_name);
            if path.exists() {
                return Ok(path);
            }
        }
    }

    // 3. 当前工作目录
    let bin_name = if cfg!(windows) { "zhihu-backend.exe" } else { "zhihu-backend" };
    let path = std::env::current_dir()?.join("bin").join(bin_name);
    if path.exists() {
        return Ok(path);
    }

    Err(AppError::Backend("找不到后端可执行文件".to_string()))
}
