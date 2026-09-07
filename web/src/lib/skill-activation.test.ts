import assert from 'node:assert/strict';
import test from 'node:test';
import { setSkillEnabled } from './skill-activation';

test('activation requires a confirmed successful write', async () => {
  const original = globalThis.fetch;
  try {
    for (const response of [
      new Response('failure', { status: 500 }),
      Response.json({ success: false }),
      Response.json({}),
    ]) {
      globalThis.fetch = async () => response;
      await assert.rejects(setSkillEnabled('source-brief', true));
    }
    globalThis.fetch = async () => { throw new Error('offline'); };
    await assert.rejects(setSkillEnabled('source-brief', true));
  } finally {
    globalThis.fetch = original;
  }
});

test('activation sends only the requested local id and boolean', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (input, init) => {
      assert.equal(input, '/api/skills/source-brief/toggle?enabled=true');
      assert.equal(init?.method, 'POST');
      return Response.json({ success: true });
    };
    await setSkillEnabled('source-brief', true);
  } finally {
    globalThis.fetch = original;
  }
});
