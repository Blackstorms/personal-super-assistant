/**
 * 从工作空间加载 composer 默认绑定；会话绑定反填。
 * 专家仅提供人设，不再从专家继承技能 / 连接器 / 资料库。
 */
import { apiRequest } from './api'

export type ComposerBindingDefaults = {
  expertId: string
  skillIds: string[]
  mcpIds: string[]
  knowledgeIds: string[]
  modelProfileId?: string
}

export type SessionComposerBindings = {
  expert_id?: string | null
  skill_ids?: string[] | null
  mcp_ids?: string[] | null
  knowledge_ids?: string[] | null
  model_profile_id?: string | null
}

type Workspace = {
  id: string
  expert_id?: string | null
  skill_ids: string[]
  mcp_ids: string[]
  knowledge_ids: string[]
}

type SessionDetail = {
  id: string
  workspace_id?: string | null
  composer_bindings?: SessionComposerBindings | null
}

export const emptyComposerBindings = (): ComposerBindingDefaults => ({
  expertId: '',
  skillIds: [],
  mcpIds: [],
  knowledgeIds: [],
})

/** 将会话持久化的 composer_bindings 转为 UI 状态（null 字段视为空数组）。 */
export function sessionBindingsToComposer(
  b: SessionComposerBindings | null | undefined,
): ComposerBindingDefaults | null {
  if (!b) return null
  // 仅当存在显式选择（含空数组）时反填；全 null 表示未记忆 / 继承
  const explicit =
    Boolean(b.expert_id) ||
    b.skill_ids != null ||
    b.mcp_ids != null ||
    b.knowledge_ids != null ||
    Boolean(b.model_profile_id)
  if (!explicit) return null
  return {
    expertId: b.expert_id || '',
    skillIds: b.skill_ids ?? [],
    mcpIds: b.mcp_ids ?? [],
    knowledgeIds: b.knowledge_ids ?? [],
    modelProfileId: b.model_profile_id || undefined,
  }
}

export async function fetchSessionComposerDefaults(
  sessionId: string,
): Promise<ComposerBindingDefaults | null> {
  const s = await apiRequest<SessionDetail>('GET', `/api/v1/sessions/${sessionId}`)
  return sessionBindingsToComposer(s.composer_bindings)
}

/** 工作空间默认绑定（专家不再补全技能 / 连接器 / 资料库）。 */
export async function fetchWorkspaceComposerDefaults(
  workspaceId: string,
): Promise<ComposerBindingDefaults> {
  const { items } = await apiRequest<{ items: Workspace[] }>('GET', '/api/v1/workspaces')
  const ws = items.find((w) => w.id === workspaceId)
  if (!ws) return emptyComposerBindings()

  return {
    expertId: ws.expert_id || '',
    skillIds: ws.skill_ids || [],
    mcpIds: ws.mcp_ids || [],
    knowledgeIds: ws.knowledge_ids || [],
  }
}
