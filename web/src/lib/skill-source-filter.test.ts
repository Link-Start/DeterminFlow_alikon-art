import assert from 'node:assert/strict';
import test from 'node:test';

import {
  filterSkillsBySource,
  skillMatchesSource,
  skillSourceFilterForOpen,
  type SkillSourceKind,
} from './skill-source-filter';

interface TestSkill {
  id: string;
  provenance?: { source?: { kind?: SkillSourceKind } } | null;
}

const skills: TestSkill[] = [
  { id: 'builtin', provenance: { source: { kind: 'core' } } },
  { id: 'local' },
  { id: 'marketplace', provenance: { source: { kind: 'marketplace' } } },
  { id: 'plugin', provenance: { source: { kind: 'plugin' } } },
];

test('filters skills into the three user-facing source groups', () => {
  assert.deepEqual(filterSkillsBySource(skills, 'all').map(({ id }) => id), [
    'builtin',
    'local',
    'marketplace',
    'plugin',
  ]);
  assert.deepEqual(filterSkillsBySource(skills, 'core').map(({ id }) => id), ['builtin']);
  assert.deepEqual(filterSkillsBySource(skills, 'local').map(({ id }) => id), ['local']);
  assert.deepEqual(filterSkillsBySource(skills, 'marketplace').map(({ id }) => id), ['marketplace']);
});

test('treats missing provenance as a local skill', () => {
  assert.equal(skillMatchesSource({ provenance: null }, 'local'), true);
});

test('opening an installed skill selects the matching source filter', () => {
  assert.equal(skillSourceFilterForOpen({ provenance: { source: { kind: 'marketplace' } } }), 'marketplace');
  assert.equal(skillSourceFilterForOpen({ provenance: { source: { kind: 'core' } } }), 'core');
  assert.equal(skillSourceFilterForOpen({ provenance: { source: { kind: 'local' } } }), 'all');
  assert.equal(skillSourceFilterForOpen(undefined), 'all');
});
