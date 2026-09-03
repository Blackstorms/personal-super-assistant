import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * 开发态：仅启动 Vite 渲染进程。
 * Electron Main 由 `npm run electron:dev` 通过 electron/dev-main.cjs 单独拉起，
 * 避免 vite-plugin-electron 打包后 require('electron') 异常。
 */
export default defineConfig(({ command }) => {
  // 安装包默认展示登录页（开发态仍由 install.sh 的 VITE_PSA_SHOW_LOGIN 控制）
  if (command === 'build' && process.env.VITE_PSA_SHOW_LOGIN !== '0') {
    process.env.VITE_PSA_SHOW_LOGIN = '1'
  }
  return {
    plugins: [react()],
    // Electron 生产环境用 loadFile(file://)，必须相对路径，否则 /assets/*.js 会打到磁盘根目录导致白屏
    base: './',
    server: { host: '127.0.0.1', port: 5173, strictPort: true },
    build: { outDir: 'dist' },
  }
})
