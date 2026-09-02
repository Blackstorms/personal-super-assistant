/**
 * 开发态 Electron 入口（可选，与 vite-plugin-electron 二选一）。
 * 优先使用 server/.venv 中的 Python，避免系统 python3 无 uvicorn。
 */
const { app, BrowserWindow, dialog, ipcMain, nativeTheme } = require('electron')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const http = require('node:http')
const net = require('node:net')
const path = require('node:path')

const PORT = 18765
const BASE = `http://127.0.0.1:${PORT}`
let win = null
let backend = null
let token = ''
const activeStreams = new Map()

function resolvePython(serverDir) {
  const win32 = process.platform === 'win32'
  for (const venvName of ['.venv312', '.venv']) {
    const venvPy = path.join(serverDir, venvName, win32 ? 'Scripts/python.exe' : 'bin/python')
    if (fs.existsSync(venvPy)) return venvPy
  }
  return win32 ? 'python' : 'python3'
}

function backendEnv(serverDir) {
  return {
    ...process.env,
    PYTHONPATH: serverDir,
    HTTP_PROXY: '',
    HTTPS_PROXY: '',
    ALL_PROXY: '',
    http_proxy: '',
    https_proxy: '',
    all_proxy: '',
  }
}

async function waitHealth(timeoutMs = 45000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    const ok = await new Promise((resolve) => {
      const req = http.get(`${BASE}/api/v1/health`, (res) => resolve(res.statusCode === 200))
      req.on('error', () => resolve(false))
      req.setTimeout(1000, () => {
        req.destroy()
        resolve(false)
      })
    })
    if (ok) return true
    await new Promise((r) => setTimeout(r, 400))
  }
  return false
}

async function isPortInUse(port) {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host: '127.0.0.1' })
    socket.once('connect', () => {
      socket.destroy()
      resolve(true)
    })
    socket.once('error', () => resolve(false))
    socket.setTimeout(800, () => {
      socket.destroy()
      resolve(false)
    })
  })
}

async function startBackend() {
  if (backend) {
    backend.kill()
    backend = null
  }
  // 端口已有进程时优先复用，避免 kill -9 Electron 后遗留 python 导致 EADDRINUSE
  if (await waitHealth(1500)) {
    return
  }
  if (await isPortInUse(PORT)) {
    const ok = await waitHealth(15000)
    if (ok) return
    throw new Error(
      `127.0.0.1:${PORT} 已被占用且健康检查失败。请先结束旧后端：lsof -tiTCP:${PORT} -sTCP:LISTEN | xargs kill -9`,
    )
  }
  const serverDir = path.resolve(__dirname, '../../../server')
  const py = resolvePython(serverDir)
  console.log('[backend] using python:', py, 'cwd:', serverDir)
  backend = spawn(py, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(PORT)], {
    cwd: serverDir,
    env: backendEnv(serverDir),
    stdio: 'pipe',
  })
  backend.stdout.on('data', (d) => console.log('[backend]', d.toString()))
  backend.stderr.on('data', (d) => console.error('[backend]', d.toString()))
  backend.on('exit', (code) => {
    console.log('[backend] exited', code)
    backend = null
  })
  const ok = await waitHealth()
  if (!ok) {
    if (backend) {
      backend.kill()
      backend = null
    }
    throw new Error('backend failed — 请确认 server/.venv 已安装依赖')
  }
}

async function loadRenderer(target) {
  const url = 'http://127.0.0.1:5173'
  for (let i = 0; i < 40; i++) {
    try {
      await target.loadURL(url)
      return
    } catch {
      await new Promise((r) => setTimeout(r, 250))
    }
  }
  throw new Error(`无法加载前端 ${url}`)
}

function createWindow() {
  win = new BrowserWindow({
    width: 1280,
    height: 840,
    webPreferences: {
      preload: path.join(__dirname, 'dev-preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  void loadRenderer(win)
}

app.whenReady().then(async () => {
  try {
    await startBackend()
  } catch (e) {
    console.error(e)
  }
  createWindow()
  ipcMain.handle('backend:status', async () => ({ healthy: await waitHealth(1500), port: PORT, hasToken: !!token }))
  ipcMain.handle('backend:restart', async () => {
    await startBackend()
    return { ok: true }
  })
  ipcMain.handle('auth:setToken', async (_e, value) => {
    token = value || ''
    return { ok: true }
  })
  ipcMain.handle('auth:clearToken', async () => {
    token = ''
    return { ok: true }
  })
  ipcMain.handle('theme:setSource', async (_e, source) => {
    if (source === 'system' || source === 'light' || source === 'dark') {
      nativeTheme.themeSource = source
    }
    return { ok: true }
  })
  ipcMain.handle('dialog:selectDirectory', async () => {
    const res = await dialog.showOpenDialog({ properties: ['openDirectory'] })
    return res.canceled ? null : res.filePaths[0]
  })
  ipcMain.handle('dialog:selectFiles', async () => {
    const res = await dialog.showOpenDialog({
      properties: ['openFile', 'openDirectory', 'multiSelections'],
    })
    return res.canceled || !res.filePaths.length ? null : res.filePaths
  })
  ipcMain.handle('api:request', async (_e, payload) => {
    const bodyStr = payload.body !== undefined ? JSON.stringify(payload.body) : undefined
    const url = new URL(BASE + payload.path)
    return await new Promise((resolve, reject) => {
      const req = http.request(
        {
          hostname: url.hostname,
          port: url.port,
          path: url.pathname + url.search,
          method: payload.method,
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
            'Content-Type': 'application/json',
            ...(bodyStr ? { 'Content-Length': Buffer.byteLength(bodyStr) } : {}),
          },
        },
        (res) => {
          let raw = ''
          res.on('data', (c) => (raw += c))
          res.on('end', () => {
            let json = raw
            try {
              json = raw ? JSON.parse(raw) : null
            } catch {}
            resolve({ status: res.statusCode, json })
          })
        },
      )
      req.on('error', reject)
      if (bodyStr) req.write(bodyStr)
      req.end()
    })
  })
  ipcMain.handle('api:stream', async (event, payload) => {
    const bodyStr = JSON.stringify(payload.body)
    const url = new URL(BASE + payload.path)
    return await new Promise((resolve, reject) => {
      const req = http.request(
        {
          hostname: url.hostname,
          port: url.port,
          path: url.pathname,
          method: 'POST',
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
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
                  event.sender.send('api:stream:event', { requestId: payload.requestId, event: ev, data })
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
                  event.sender.send('api:stream:event', { requestId: payload.requestId, event: ev, data })
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
        if (err?.message === 'aborted' || err?.code === 'ECONNRESET') {
          resolve({ ok: true, aborted: true })
          return
        }
        reject(err)
      })
      req.write(bodyStr)
      req.end()
    })
  })

  ipcMain.handle('api:stream:abort', async (_e, requestId) => {
    const req = activeStreams.get(requestId)
    if (req) {
      activeStreams.delete(requestId)
      req.destroy()
    }
    return { ok: true }
  })
})

app.on('before-quit', () => {
  if (backend) backend.kill()
})

app.on('window-all-closed', () => {
  if (backend) backend.kill()
  if (process.platform !== 'darwin') app.quit()
})
