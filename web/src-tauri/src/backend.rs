//! 后端进程管理器
//!
//! 负责管理 Python FastAPI 后端子进程的生命周期
//! - 启动子进程
//! - 监控进程状态
//! - 优雅停止

use std::process::Child;
use std::sync::Mutex;

use crate::commands::BackendStatus;

/// 后端进程管理器
pub struct BackendManager {
    child: Mutex<Option<Child>>,
    port: u16,
    host: String,
}

impl BackendManager {
    /// 创建空的 BackendManager（用于 start_backend 初始化）
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
            port: 38080,
            host: "127.0.0.1".to_string(),
        }
    }

    /// 使用已启动的子进程构造
    pub fn with_child(self, child: Child) -> Self {
        Self {
            child: Mutex::new(Some(child)),
            ..self
        }
    }

    /// 停止后端进程
    pub fn stop(&self) -> Result<(), String> {
        let mut guard = self.child.lock().map_err(|e| e.to_string())?;
        if let Some(mut child) = guard.take() {
            child.kill().map_err(|e| e.to_string())?;
            log::info!("后端进程已停止");
        }
        Ok(())
    }

    /// 获取后端状态
    pub fn status(&self) -> BackendStatus {
        let guard = self.child.lock().ok();
        match guard {
            Some(guard) => match guard.as_ref() {
                Some(child) => BackendStatus {
                    running: true,
                    pid: Some(child.id()),
                    port: Some(self.port),
                    host: Some(self.host.clone()),
                },
                None => BackendStatus {
                    running: false,
                    pid: None,
                    port: None,
                    host: None,
                },
            },
            None => BackendStatus {
                running: false,
                pid: None,
                port: None,
                host: None,
            },
        }
    }
}

impl Default for BackendManager {
    fn default() -> Self {
        Self::new()
    }
}

impl Drop for BackendManager {
    fn drop(&mut self) {
        // 析构时确保子进程被清理
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}
