export const SCIENCE_MODE = import.meta.env.VITE_RESEARCH_PROFILE !== 'industry'
export type ResearchProfileId = 'science' | 'remote_sensing' | 'industry'
export const RESEARCH_PROFILE_LABELS: Record<ResearchProfileId, string> = {
  science: '科研背景调研', remote_sensing: '科研背景调研 · 遥感', industry: '行业调研',
}
export function researchProfileId(value: unknown): ResearchProfileId | undefined {
  return value === 'science' || value === 'remote_sensing' || value === 'industry' ? value : undefined
}
// Old checkpoints predate the scientific profile and used the industry workflow.
export function checkpointResearchProfile(state?: Record<string, unknown>): ResearchProfileId {
  const profile = state?.research_profile as Record<string, unknown> | undefined
  return researchProfileId(profile?.profile_id) || researchProfileId(state?.profile_id)
    || (profile?.mode === 'science' ? 'science' : 'industry')
}
export const DEMO_QUERY = '围绕2020-2026年光学遥感图像变化检测方法开展文献调研，生成文献综述。'
export const RESEARCH_QUESTIONS = [
  DEMO_QUERY,
  '提出并验证遥感变化检测跨场景泛化的研究假设，比较支持证据、反例与适用条件。',
  '结合知识库论文梳理研究方法、实验条件与证据缺口，生成带真实引用的综述。',
]
