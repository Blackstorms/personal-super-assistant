import { apiRequest } from './api'
import { useAppStore } from '../stores/app'

/** 删除会话并清理本地缓存；返回是否删除的是当前查看的会话 */
export async function deleteSession(sessionId: string): Promise<boolean> {
  await apiRequest('DELETE', `/api/v1/sessions/${sessionId}`)
  const wasCurrent = useAppStore.getState().sessionId === sessionId
  useAppStore.getState().removeSession(sessionId)
  return wasCurrent
}
