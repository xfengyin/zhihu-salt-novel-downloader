import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
// Vite 配置
// - 端口使用 5173（避免与后端 3000 冲突）
// - /api 代理到后端 FastAPI 服务（http://localhost:3000）
// - /docs 与 /openapi.json 代理到后端 Swagger
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './src'),
        },
    },
    server: {
        port: 5173,
        strictPort: false,
        host: '0.0.0.0',
        proxy: {
            '/api': {
                target: 'http://localhost:3000',
                changeOrigin: true,
                secure: false,
            },
            '/docs': {
                target: 'http://localhost:3000',
                changeOrigin: true,
                secure: false,
            },
            '/openapi.json': {
                target: 'http://localhost:3000',
                changeOrigin: true,
                secure: false,
            },
        },
    },
    build: {
        outDir: 'dist',
        sourcemap: true,
        chunkSizeWarningLimit: 1000,
        rollupOptions: {
            output: {
                manualChunks: {
                    react: ['react', 'react-dom', 'react-router-dom'],
                    query: ['@tanstack/react-query'],
                    ui: ['@radix-ui/react-label', '@radix-ui/react-progress', '@radix-ui/react-select', '@radix-ui/react-switch', '@radix-ui/react-tabs', '@radix-ui/react-tooltip'],
                },
            },
        },
    },
    optimizeDeps: {
        include: ['react', 'react-dom', 'react-router-dom', 'zustand', 'axios', 'i18next', 'react-i18next'],
    },
});
