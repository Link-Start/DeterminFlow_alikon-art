export type SkillSourceKind = 'local' | 'core' | 'plugin' | 'marketplace';

export type SkillSourceFilter = 'all' | Extract<SkillSourceKind, 'local' | 'core' | 'marketplace'>;

export interface SkillWithSource {
  provenance?: {
    source?: {
      kind?: SkillSourceKind;
    };
  } | null;
}

export const skillSourceFilters: ReadonlyArray<{
  value: SkillSourceFilter;
  label: string;
}> = [
  { value: 'all', label: '全部' },
  { value: 'core', label: '内置' },
  { value: 'local', label: '本地' },
  { value: 'marketplace', label: '广场下载' },
];

export function skillMatchesSource(
  skill: SkillWithSource,
  filter: SkillSourceFilter,
): boolean {
  if (filter === 'all') {
    return true;
  }
  return (skill.provenance?.source?.kind ?? 'local') === filter;
}

export function filterSkillsBySource<T extends SkillWithSource>(
  skills: T[],
  filter: SkillSourceFilter,
): T[] {
  return filter === 'all'
    ? skills
    : skills.filter((skill) => skillMatchesSource(skill, filter));
}

export function skillSourceFilterForOpen(
  skill: SkillWithSource | undefined,
): SkillSourceFilter {
  const kind = skill?.provenance?.source?.kind;
  if (kind === 'core' || kind === 'marketplace') {
    return kind;
  }
  return 'all';
}
