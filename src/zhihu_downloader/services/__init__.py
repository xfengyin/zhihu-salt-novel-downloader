"""Service 层 - 业务编排

本层封装核心业务流程（下载编排、书架管理），对上为 API 层和 CLI 层提供能力，
对下编排 core/parsers/exporters 等领域组件。不依赖 HTTP/CLI 框架，可独立测试。
"""
