//! Tauri 桌面端主入口
//!
//! 职责：
//! - 注册 Tauri 插件（dialog、fs、shell、notification、store、os、log）
//! - 提供内置命令（启动/停止后端、打开下载目录）
//! - 托盘菜单支持
//!
//! 设计原则：
//! - 后端进程由 Rust 端管理，避免前端页面刷新时丢失后端
//! - 窗口配置、主题、安全策略集中在 tauri.conf.json

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, RunEvent, WindowEvent,
};
use tauri_plugin_log::{Target, TargetKind};

mod backend;
mod commands;
mod error;

use error::AppResult;

/// 应用主入口
pub fn run() {
    let context = tauri::generate_context!();

    tauri::Builder::default()
        // 日志插件
        .plugin(
            tauri_plugin_log::Builder::new()
                .targets([
                    Target::new(TargetKind::Stdout),
                    Target::new(TargetKind::LogDir { file_name: None }),
                ])
                .level(log::LevelFilter::Info)
                .build(),
        )
        // 官方插件
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_os::init())
        // 后端进程管理
        .setup(|app| {
            log::info!("Tauri 应用启动");

            // 构建托盘菜单
            let show_item = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>)?;
            let hide_item = MenuItem::with_id(app, "hide", "隐藏到托盘", true, None::<&str>)?;
            let separator = PredefinedMenuItem::separator(app)?;
            let quit_item = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(
                app,
                &[&show_item, &hide_item, &separator, &quit_item],
            )?;

            // 注册托盘图标
            let _tray = TrayIconBuilder::with_id("main-tray")
                .menu(&menu)
                .menu_on_left_click(false)
                .tooltip("知乎盐选小说下载器")
                .icon(app.default_window_icon().cloned().unwrap_or_else(|| {
                    tauri::image::Image::from_bytes(include_bytes!("../icons/icon.png"))
                        .expect("Failed to load icon")
                }))
                .on_menu_event(|app, event| {
                    match event.id.as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "hide" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.hide();
                            }
                        }
                        "quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            if window.is_visible().unwrap_or(false) {
                                let _ = window.set_focus();
                            } else {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        // 注册 Tauri 命令
        .invoke_handler(tauri::generate_handler![
            commands::start_backend,
            commands::stop_backend,
            commands::get_backend_status,
            commands::open_download_dir,
            commands::get_app_version,
            commands::get_platform_info,
        ])
        .build(context)
        .expect("Tauri 应用初始化失败")
        .run(on_window_event);
}

/// 窗口事件处理
fn on_window_event(app: &AppHandle, event: WindowEvent) {
    if let WindowEvent::CloseRequested { api, .. } = event {
        // 关闭主窗口时隐藏到托盘（不退出进程）
        if let Some(window) = app.get_webview_window("main") {
            if window.label() == "main" {
                let _ = window.hide();
                api.prevent_close();
                log::info!("窗口已最小化到托盘");
            }
        }
    }
}

/// 应用退出钩子
pub fn on_run_event(_app: &AppHandle, _event: RunEvent) {
    // 这里可以处理应用退出时的资源清理
}
