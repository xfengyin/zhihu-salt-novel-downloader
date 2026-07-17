//! 错误类型模块
//!
//! 统一的错误处理，序列化到前端时返回清晰的错误信息

use serde::{Deserialize, Serialize};

/// 应用错误类型
#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("后端错误: {0}")]
    Backend(String),

    #[error("IO 错误: {0}")]
    Io(String),

    #[error("Shell 错误: {0}")]
    Shell(String),

    #[error("路径错误: {0}")]
    Path(String),

    #[error("Tauri 错误: {0}")]
    Tauri(String),

    #[error("配置错误: {0}")]
    Config(String),
}

impl From<tauri::Error> for AppError {
    fn from(err: tauri::Error) -> Self {
        AppError::Tauri(err.to_string())
    }
}

impl From<std::io::Error> for AppError {
    fn from(err: std::io::Error) -> Self {
        AppError::Io(err.to_string())
    }
}

impl Serialize for AppError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        #[derive(Serialize, Deserialize)]
        struct ErrorPayload {
            kind: String,
            message: String,
        }
        ErrorPayload {
            kind: match self {
                AppError::Backend(_) => "backend".to_string(),
                AppError::Io(_) => "io".to_string(),
                AppError::Shell(_) => "shell".to_string(),
                AppError::Path(_) => "path".to_string(),
                AppError::Tauri(_) => "tauri".to_string(),
                AppError::Config(_) => "config".to_string(),
            },
            message: self.to_string(),
        }
        .serialize(serializer)
    }
}

pub type AppResult<T> = std::result::Result<T, AppError>;
