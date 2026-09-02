/**
 * 本地文件夹 → 白名单 + 工作空间（root_paths）。
 * 选择文件夹时应延迟创建空间：仅暂存路径，首次发消息时再 ensureFolderWorkspace。
 */
import { apiRequest } from './api'

export type WorkspaceItem = {
  id: string
  name: string
  status?: string
  root_paths?: string[]
  description?: string | null
}

export function folderBasename(path: string): string {
  const cleaned = path.replace(/[/\\]+$/, '')
  const parts = cleaned.split(/[/\\]/)
  return parts[parts.length - 1] || cleaned || '未命名文件夹'
}

export function isFolderWorkspace(ws: { root_paths?: string[] | null }): boolean {
  return Boolean(ws.root_paths && ws.root_paths.length > 0)
}

function normPath(p: string): string {
  return p.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

export function findWorkspaceByRootPath(items: WorkspaceItem[], path: string): WorkspaceItem | undefined {
  const target = normPath(path)
  return items.find((w) => (w.root_paths || []).some((r) => normPath(r) === target))
}

/** 将路径加入全局白名单（已存在则跳过） */
export async function ensureWhitelistRoot(path: string): Promise<string[]> {
  const w = await apiRequest<{ roots: string[] }>('GET', '/api/v1/settings/whitelist')
  const roots = w.roots || []
  if (roots.some((r) => normPath(r) === normPath(path))) return roots
  const next = [...roots, path]
  await apiRequest('PUT', '/api/v1/settings/whitelist', { roots: next })
  return next
}

/** 按 root_path 查找或创建文件夹型工作空间，并确保加入白名单 */
export async function ensureFolderWorkspace(path: string): Promise<WorkspaceItem> {
  await ensureWhitelistRoot(path)
  const listed = await apiRequest<{ items: WorkspaceItem[] }>('GET', '/api/v1/workspaces')
  const active = (listed.items || []).filter((w) => w.status === 'active' || !w.status)
  const existing = findWorkspaceByRootPath(active, path)
  if (existing) return existing
  return apiRequest<WorkspaceItem>('POST', '/api/v1/workspaces', {
    name: folderBasename(path),
    description: path,
    root_paths: [path],
  })
}

/** 系统目录选择器，仅返回路径（不写库、不建空间） */
export async function pickLocalFolderPath(): Promise<string | null> {
  const dir = window.api?.selectDirectory
    ? await window.api.selectDirectory()
    : typeof window !== 'undefined'
      ? window.prompt('输入本地文件夹绝对路径')
      : null
  return dir || null
}
