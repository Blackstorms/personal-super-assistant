/** 模块页范围：null=全部，STANDALONE_SCOPE=独立任务，其余为工作空间 id。 */
export const STANDALONE_SCOPE = '__standalone__' as const

export type ModuleScopeId = string | null

export function isStandaloneScope(scopeId: ModuleScopeId): boolean {
  return scopeId === STANDALONE_SCOPE
}

export function isAllScope(scopeId: ModuleScopeId): boolean {
  return scopeId === null
}

export function isWorkspaceScope(scopeId: ModuleScopeId): scopeId is string {
  return scopeId !== null && scopeId !== STANDALONE_SCOPE
}

/** 侧栏 workspaceId 同步到模块范围：无工作空间时默认「独立任务」。 */
export function scopeFromSidebarWorkspace(workspaceId: string | null): ModuleScopeId {
  return workspaceId ?? STANDALONE_SCOPE
}

export function scopeCrumbLabel(scopeId: ModuleScopeId, workspaceName?: string): string {
  if (isAllScope(scopeId)) return '全部'
  if (isStandaloneScope(scopeId)) return '独立任务'
  return workspaceName || '工作空间'
}

export function appendScopeQuery(qs: URLSearchParams, scopeId: ModuleScopeId) {
  if (isStandaloneScope(scopeId)) {
    qs.set('standalone', 'true')
  } else if (isWorkspaceScope(scopeId)) {
    qs.set('workspace_id', scopeId)
  }
}

export function scopeQueryString(scopeId: ModuleScopeId): string {
  const qs = new URLSearchParams()
  appendScopeQuery(qs, scopeId)
  const s = qs.toString()
  return s ? `?${s}` : ''
}

/** POST 创建时写入的 workspace_id（独立任务为 null）。 */
export function scopeWorkspaceIdForCreate(scopeId: ModuleScopeId): string | null {
  if (isWorkspaceScope(scopeId)) return scopeId
  return null
}

export function scopeBodyForExport(scopeId: ModuleScopeId): {
  workspace_id?: string | null
  standalone?: boolean
} {
  if (isStandaloneScope(scopeId)) return { standalone: true, workspace_id: null }
  if (isWorkspaceScope(scopeId)) return { workspace_id: scopeId }
  return {}
}

export function filterSessionsByScope<T extends { workspace_id?: string | null }>(
  sessions: T[],
  scopeId: ModuleScopeId,
): T[] {
  if (isStandaloneScope(scopeId)) return sessions.filter((s) => !s.workspace_id)
  if (isWorkspaceScope(scopeId)) return sessions.filter((s) => s.workspace_id === scopeId)
  return sessions
}

/** SessionPickTree：独立任务传 STANDALONE_SCOPE，指定空间传 id，全部传 null。 */
export function scopeForSessionPick(scopeId: ModuleScopeId): ModuleScopeId {
  return scopeId
}
