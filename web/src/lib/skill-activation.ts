export async function setSkillEnabled(skillId: string, enabled: boolean): Promise<void> {
  const response = await fetch(
    `/api/skills/${encodeURIComponent(skillId)}/toggle?enabled=${enabled}`,
    { method: 'POST' },
  );
  if (!response.ok) throw new Error('Skill 状态未更新，请重试。');
  const body: unknown = await response.json();
  if (!body || typeof body !== 'object' || !('success' in body) || body.success !== true) {
    throw new Error('未能确认 Skill 状态，请刷新后重试。');
  }
}
