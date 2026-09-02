/**
 * Electron Main 进程。
 *
 * 职责：
 * 1. 创建安全 BrowserWindow（contextIsolation / 无 nodeIntegration）
 * 2. 拉起并守护本地 Python FastAPI sidecar（或开发态 uvicorn）
 * 3. 提供类型化 IPC：选目录、HTTP/SSE 代理、后端状态
 */

import { app, BrowserWindow, dialog, ipcMain, nativeTheme } from 'electron'
import { ChildProcessWithoutNullStreams, spawn } from 'node:child_process'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'

// tsconfig.node.json 以 CommonJS 输出；CJS 自带 __dirname，不能用 import.meta.url

let mainWindow: BrowserWindow | null = null
let backendProc: ChildProcessWithoutNullStreams | null = null
let cachedToken = ''
let lastBackendError = ''
/** 主动停止时不自动拉起 */
let backendStopping = false
const BACKEND_PORT = 18765
const BACKEND_BASE = `http://127.0.0.1:${BACKEND_PORT}`
/** 进行中的 SSE 代理请求，供停止按钮打断 */
const activeStreams = new Map<string, http.ClientRequest>()

/** 解析 sidecar 可执行文件路径（按平台/架构）。 */
function resolveSidecarPath(): string | null {
  const platform = process.platform
  const arch = process.arch
  const name =
    platform === 'win32'
      ? 'server-win-x64.exe'
      : platform === 'darwin'
        ? arch === 'arm64'
          ? 'server-darwin-arm64'
          : 'server-darwin-x64'
        : null
  if (!name) return null

  const candidates = [
    path.join(process.resourcesPath, 'sidecars', name),
    path.join(app.getAppPath(), '..', '..', 'resources', 'sidecars', `${platform}-${arch}`, name),
    path.join(__dirname, '..', '..', '..', 'resources', 'sidecars', `${platform}-${arch}`, name),
  ]
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      try {
        fs.chmodSync(c, 0o755)
      } catch {
        /* ignore */
      }
      return c
    }
  }
  return null
}

/** 开发态：server 目录（apps/desktop -> personal-super-assistant/server）。 */
function resolveDevServerDir(): string {
  return path.resolve(__dirname, '..', '..', '..', 'server')
}

const SEARCH_ENV_KEYS = [
  'PSA_WEB_SEARCH_PROVIDER',
  'PSA_WEB_SEARCH_API_URL',
  'PSA_WEB_SEARCH_API_KEY',
  'TAVILY_API_KEY',
  'PSA_WEB_SEARCH_TRUST_ENV',
  'PSA_LLM_THINKING',
  'PSA_LLM_REASONING_EFFORT',
] as const

function userSearchEnvPath(): string {
  return path.join(os.homedir(), '.personal-super-assistant', '.env')
}

function parseDotEnv(filePath: string): Record<string, string> {
  if (!fs.existsSync(filePath)) return {}
  const out: Record<string, string> = {}
  for (const raw of fs.readFileSync(filePath, 'utf8').split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#') || !line.includes('=')) continue
    const eq = line.indexOf('=')
    const key = line.slice(0, eq).trim()
    let val = line.slice(eq + 1).trim()
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1)
    }
    if (key) out[key] = val
  }
  return out
}

/** 开发态把 server/.env 的搜索 Key 同步到用户目录，打包后 sidecar 仍能读到。 */
function syncSearchEnvToUserDir(): void {
  if (app.isPackaged) return
  const src = parseDotEnv(path.join(resolveDevServerDir(), '.env'))
  const destPath = userSearchEnvPath()
  const dest = parseDotEnv(destPath)
  let changed = false
  for (const key of SEARCH_ENV_KEYS) {
    const val = src[key]
    if (val && !dest[key]) {
      dest[key] = val
      changed = true
    }
  }
  if (!changed) return
  try {
    fs.mkdirSync(path.dirname(destPath), { recursive: true })
    const body = Object.entries(dest)
      .map(([k, v]) => `${k}=${v}`)
      .join('\n')
    fs.writeFileSync(destPath, `${body}\n`, 'utf8')
  } catch {
    /* ignore */
  }
}

function applySearchEnv(into: NodeJS.ProcessEnv, filePath: string): void {
  const parsed = parseDotEnv(filePath)
  for (const key of SEARCH_ENV_KEYS) {
    const val = parsed[key]
    if (val && !into[key]) into[key] = val
  }
}

/** Finder 启动 PATH 不含 Homebrew/nvm，MCP 的 npx/uvx 会找不到。 */
function augmentGuiPath(current: string | undefined): string {
  const home = os.homedir()
  const extras: string[] = []
  if (process.platform === 'darwin') {
    extras.push('/opt/homebrew/bin', '/usr/local/bin', path.join(home, '.local', 'bin'))
    const nvmCurrent = path.join(home, '.nvm', 'current', 'bin')
    extras.push(nvmCurrent)
    const nvmVersions = path.join(home, '.nvm', 'versions', 'node')
    if (fs.existsSync(nvmVersions)) {
      const latest = fs
        .readdirSync(nvmVersions)
        .filter((name) => fs.existsSync(path.join(nvmVersions, name, 'bin')))
        .sort()
        .pop()
      if (latest) extras.push(path.join(nvmVersions, latest, 'bin'))
    }
  } else if (process.platform === 'win32') {
    extras.push(
      path.join(process.env.ProgramFiles || 'C:\\Program Files', 'nodejs'),
      path.join(process.env.LOCALAPPDATA || path.join(home, 'AppData', 'Local'), 'Programs', 'nodejs'),
      path.join(process.env.APPDATA || path.join(home, 'AppData', 'Roaming'), 'npm'),
      path.join(home, '.local', 'bin'),
    )
  } else {
    extras.push('/usr/local/bin', path.join(home, '.local', 'bin'))
  }
  const parts = (current || '').split(path.delimiter).filter(Boolean)
  for (const extra of extras.reverse()) {
    if (fs.existsSync(extra) && !parts.includes(extra)) parts.unshift(extra)
  }
  return parts.join(path.delimiter)
}

/** 后端环境：仅 PYTHONPATH；Hermes 使用仓库内 third_party/hermes-agent。 */
function backendEnv(serverDir?: string): NodeJS.ProcessEnv {
  syncSearchEnvToUserDir()
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    PSA_PORT: String(BACKEND_PORT),
    ...(serverDir ? { PYTHONPATH: serverDir } : {}),
    // 避免继承 Cursor 终端注入的本地代理，导致 web_search 外网超时/403
    HTTP_PROXY: '',
    HTTPS_PROXY: '',
    ALL_PROXY: '',
    http_proxy: '',
    https_proxy: '',
    all_proxy: '',
  }
  env.PATH = augmentGuiPath(env.PATH)
  applySearchEnv(env, userSearchEnvPath())
  if (serverDir) applySearchEnv(env, path.join(serverDir, '.env'))
  return env
}

/** 优先使用项目 venv 中的 Python，避免系统 python3 无 uvicorn。 */
function resolvePython(serverDir: string): string {
  const win = process.platform === 'win32'
  for (const venvName of ['.venv312', '.venv']) {
    const venvPy = path.join(serverDir, venvName, win ? 'Scripts/python.exe' : 'bin/python')
    if (fs.existsSync(venvPy)) return venvPy
  }
  return win ? 'python' : 'python3'
}

function probeHealth(timeoutMs = 800): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`${BACKEND_BASE}/api/v1/health`, (res) => {
      resolve(res.statusCode === 200)
    })
    req.on('error', () => resolve(false))
    req.setTimeout(timeoutMs, () => {
      req.destroy()
      resolve(false)
    })
  })
}

async function waitHealth(timeoutMs = 45000): Promise<boolean> {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (await probeHealth(1000)) return true
    await new Promise((r) => setTimeout(r, 400))
  }
  return false
}

async function startBackend(): Promise<void> {
  // 若已有健康后端（手动启动），直接复用
  if (await waitHealth(1500)) {
    return
  }
  backendStopping = true
  if (backendProc) stopBackend()
  backendStopping = false
  const sidecar = resolveSidecarPath()
  lastBackendError = ''
  if (sidecar) {
    console.log('[backend] sidecar', sidecar)
    backendProc = spawn(sidecar, [], {
      env: backendEnv(),
      stdio: 'pipe',
    })
  } else {
    const serverDir = resolveDevServerDir()
    const py = resolvePython(serverDir)
    console.log('[backend] using python:', py, 'cwd:', serverDir)
    // 不用 --reload：改代码时会杀进程，导致进行中的对话 SSE 断连
    backendProc = spawn(
      py,
      ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)],
      {
        cwd: serverDir,
        env: backendEnv(serverDir),
        stdio: 'pipe',
      },
    )
  }
  backendProc.stdout.on('data', (d) => console.log('[backend]', d.toString()))
  backendProc.stderr.on('data', (d) => {
    const text = d.toString()
    console.error('[backend]', text)
    lastBackendError = text.trim().slice(-500) || lastBackendError
  })
  backendProc.on('exit', (code) => {
    console.log('[backend] exited', code)
    if (!lastBackendError) lastBackendError = `sidecar exited (${code ?? 'null'})`
    backendProc = null
    if (backendStopping) return
    if (mainWindow && !mainWindow.isDestroyed()) {
      void startBackend().catch((e) => console.error('[backend] auto-restart failed', e))
    }
  })
  const ok = await waitHealth()
  if (!ok) {
    stopBackend()
    throw new Error(
      'backend health check failed — 请先执行: cd server && source .venv/bin/activate && pip install -r requirements.txt',
    )
  }
}

function stopBackend() {
  backendStopping = true
  if (backendProc) {
    backendProc.kill()
    backendProc = null
  }
}

async function loadRenderer(win: BrowserWindow) {
  const devUrl = process.env.VITE_DEV_SERVER_URL || 'http://127.0.0.1:5173'
  if (!app.isPackaged) {
    for (let i = 0; i < 40; i++) {
      try {
        await win.loadURL(devUrl)
        return
      } catch {
        await new Promise((r) => setTimeout(r, 250))
      }
    }
    throw new Error(`无法加载前端 ${devUrl}，请确认 Vite 已启动`)
  }
  const html = path.join(__dirname, '../dist/index.html')
  if (!fs.existsSync(html)) {
    throw new Error(`renderer missing: ${html}`)
  }
  await win.loadFile(html)
}

function attachRendererDiagnostics(win: BrowserWindow) {
  win.webContents.on('did-fail-load', (_e, code, desc, url) => {
    console.error('[renderer] did-fail-load', code, desc, url)
  })
  win.webContents.on('render-process-gone', (_e, details) => {
    console.error('[renderer] gone', details)
  })
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    show: false,
    backgroundColor: '#f4f4f5',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  attachRendererDiagnostics(mainWindow)
  mainWindow.once('ready-to-show', () => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.show()
  })
  setTimeout(() => {
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) mainWindow.show()
  }, 2000)
  void loadRenderer(mainWindow).catch((e) => {
    console.error('[renderer] load failed', e)
    const win = mainWindow
    if (win && !win.isDestroyed()) {
      void win.loadURL(
        `data:text/html;charset=utf-8,${encodeURIComponent(
          `<p style="font:14px sans-serif;padding:24px">界面加载失败：${String(e)}</p>`,
        )}`,
      )
    }
  })
}

/** 通用 HTTP 代理：Renderer 不直持密钥，统一附加 Bearer。 */
function proxyRequest(payload: {
  method: string
  path: string
  body?: unknown
  headers?: Record<string, string>
}): Promise<{ status: number; json: unknown }> {
  const bodyStr = payload.body !== undefined ? JSON.stringify(payload.body) : undefined
  const url = new URL(payload.path.startsWith('http') ? payload.path : `${BACKEND_BASE}${payload.path}`)
  const opts: http.RequestOptions = {
    hostname: url.hostname,
    port: url.port,
    path: url.pathname + url.search,
    method: payload.method,
    headers: {
      ...(cachedToken ? { Authorization: `Bearer ${cachedToken}` } : {}),
      'Content-Type': 'application/json',
      ...(payload.headers || {}),
      ...(bodyStr ? { 'Content-Length': Buffer.byteLength(bodyStr) } : {}),
    },
  }
  return new Promise((resolve, reject) => {
    const req = http.request(opts, (res) => {
      let raw = ''
      res.on('data', (c) => (raw += c))
      res.on('end', () => {
        let json: unknown = raw
        try {
          json = raw ? JSON.parse(raw) : null
        } catch {
          /* keep text */
        }
        resolve({ status: res.statusCode || 500, json })
      })
    })
    req.on('error', reject)
    if (bodyStr) req.write(bodyStr)
    req.end()
  })
}

app.whenReady().then(() => {
  createWindow()
  void startBackend().catch((e) => {
    lastBackendError = String(e)
    console.error('Failed to start backend', e)
  })

  ipcMain.handle('backend:status', async () => {
    const healthy = await probeHealth(800)
    return { healthy, port: BACKEND_PORT, hasToken: Boolean(cachedToken), error: lastBackendError }
  })

  ipcMain.handle('backend:restart', async () => {
    stopBackend()
    await startBackend()
    return { ok: true }
  })

  ipcMain.handle('auth:setToken', async (_e, token: string) => {
    cachedToken = token || ''
    return { ok: true }
  })

  ipcMain.handle('auth:clearToken', async () => {
    cachedToken = ''
    return { ok: true }
  })

  ipcMain.handle('theme:setSource', async (_e, source: 'system' | 'light' | 'dark') => {
    if (source === 'system' || source === 'light' || source === 'dark') {
      nativeTheme.themeSource = source
    }
    return { ok: true }
  })

  ipcMain.handle('dialog:selectDirectory', async () => {
    const res = await dialog.showOpenDialog({ properties: ['openDirectory'] })
    if (res.canceled || !res.filePaths[0]) return null
    return res.filePaths[0]
  })

  ipcMain.handle('dialog:selectFiles', async () => {
    const res = await dialog.showOpenDialog({
      properties: ['openFile', 'openDirectory', 'multiSelections'],
    })
    if (res.canceled || !res.filePaths.length) return null
    return res.filePaths
  })

  ipcMain.handle('api:request', async (_e, payload) => proxyRequest(payload))

  /**
   * SSE 代理：将后端 event-stream 逐条转发给 Renderer（api:stream:event）。
   */
  ipcMain.handle('api:stream', async (event, payload: { path: string; body: unknown; requestId: string }) => {
    const bodyStr = JSON.stringify(payload.body)
    const url = new URL(`${BACKEND_BASE}${payload.path}`)
    return await new Promise((resolve, reject) => {
      const req = http.request(
        {
          hostname: url.hostname,
          port: url.port,
          path: url.pathname,
          method: 'POST',
          headers: {
            ...(cachedToken ? { Authorization: `Bearer ${cachedToken}` } : {}),
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
            'Content-Length': Buffer.byteLength(bodyStr),
          },
        },
        (res) => {
          let buffer = ''
          res.on('data', (chunk) => {
            buffer += chunk.toString('utf8')
            const parts = buffer.replace(/\r\n/g, '\n').split('\n\n')
            buffer = parts.pop() || ''
            for (const part of parts) {
              const lines = part.split('\n')
              let ev = 'message'
              let data = ''
              for (const line of lines) {
                if (line.startsWith('event:')) ev = line.slice(6).trim()
                if (line.startsWith('data:')) data += line.slice(5).trim()
              }
              if (data) {
                try {
                  event.sender.send('api:stream:event', {
                    requestId: payload.requestId,
                    event: ev,
                    data: JSON.parse(data),
                  })
                } catch {
                  event.sender.send('api:stream:event', {
                    requestId: payload.requestId,
                    event: ev,
                    data,
                  })
                }
              }
            }
          })
          res.on('end', () => {
            activeStreams.delete(payload.requestId)
            if (buffer.trim()) {
              const lines = buffer.replace(/\r\n/g, '\n').split('\n')
              let ev = 'message'
              let data = ''
              for (const line of lines) {
                if (line.startsWith('event:')) ev = line.slice(6).trim()
                if (line.startsWith('data:')) data += line.slice(5).trim()
              }
              if (data) {
                try {
                  event.sender.send('api:stream:event', {
                    requestId: payload.requestId,
                    event: ev,
                    data: JSON.parse(data),
                  })
                } catch {
                  event.sender.send('api:stream:event', {
                    requestId: payload.requestId,
                    event: ev,
                    data,
                  })
                }
              }
            }
            resolve({ ok: true })
          })
        },
      )
      activeStreams.set(payload.requestId, req)
      req.on('error', (err) => {
        activeStreams.delete(payload.requestId)
        // 主动 abort 时不算失败
        if ((err as NodeJS.ErrnoException).message === 'aborted' || (err as NodeJS.ErrnoException).code === 'ECONNRESET') {
          resolve({ ok: true, aborted: true })
          return
        }
        reject(err)
      })
      req.write(bodyStr)
      req.end()
    })
  })

  ipcMain.handle('api:stream:abort', async (_e, requestId: string) => {
    const req = activeStreams.get(requestId)
    if (req) {
      activeStreams.delete(requestId)
      req.destroy()
    }
    return { ok: true }
  })
})

app.on('window-all-closed', () => {
  stopBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => stopBackend())
