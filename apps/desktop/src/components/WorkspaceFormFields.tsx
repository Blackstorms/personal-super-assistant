/**
 * 工作空间（项目）创建/编辑表单字段。
 */
import BindingChipPicker from './BindingChipPicker'

export type WorkspaceFormValues = {
  name: string
  description: string
  instructions: string
  expertId: string
  skillIds: string[]
  mcpIds: string[]
  knowledgeIds: string[]
}

type Expert = { id: string; name: string }
type Skill = { id: string; name: string }
type Mcp = { id: string; name: string }
type Knowledge = { id: string; name?: string | null; path?: string; root_path?: string }

type Props = {
  values: WorkspaceFormValues
  experts: Expert[]
  skills: Skill[]
  mcps: Mcp[]
  knowledge: Knowledge[]
  onChange: (patch: Partial<WorkspaceFormValues>) => void
}

export function emptyWorkspaceForm(): WorkspaceFormValues {
  return {
    name: '',
    description: '',
    instructions: '',
    expertId: '',
    skillIds: [],
    mcpIds: [],
    knowledgeIds: [],
  }
}

export default function WorkspaceFormFields({ values, experts, skills, mcps, knowledge, onChange }: Props) {
  return (
    <div className="stack">
      <label className="muted">名称</label>
      <input
        value={values.name}
        onChange={(e) => onChange({ name: e.target.value })}
        placeholder="工作空间名称"
      />
      <label className="muted">描述</label>
      <input
        value={values.description}
        onChange={(e) => onChange({ description: e.target.value })}
        placeholder="可选"
      />
      <label className="muted">项目指令</label>
      <textarea
        value={values.instructions}
        onChange={(e) => onChange({ instructions: e.target.value })}
        placeholder="写入本工作空间的系统指令 / 方法论"
        rows={4}
      />
      <BindingChipPicker
        label="默认专家"
        kind="expert"
        options={experts}
        selectedIds={values.expertId ? [values.expertId] : []}
        onChange={(ids) => onChange({ expertId: ids[0] || '' })}
        single
        searchPlaceholder="搜索专家…"
      />
      <BindingChipPicker
        label="技能"
        kind="skill"
        options={skills}
        selectedIds={values.skillIds}
        onChange={(skillIds) => onChange({ skillIds })}
        searchPlaceholder="搜索技能并添加…"
      />
      <BindingChipPicker
        label="连接器"
        kind="mcp"
        options={mcps}
        selectedIds={values.mcpIds}
        onChange={(mcpIds) => onChange({ mcpIds })}
        searchPlaceholder="搜索连接器并添加…"
      />
      <BindingChipPicker
        label="资料库"
        kind="knowledge"
        options={knowledge.map((k) => ({
          id: k.id,
          name: k.name || k.path || k.id,
          description: k.root_path || k.path,
        }))}
        selectedIds={values.knowledgeIds}
        onChange={(knowledgeIds) => onChange({ knowledgeIds })}
        searchPlaceholder="搜索资料库并添加…"
      />
    </div>
  )
}
