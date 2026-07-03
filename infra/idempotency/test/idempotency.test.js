const { createMemoryStore } = require('../index');

describe('MemoryStore idempotency', () => {
  test('set and get works', async () => {
    const s = createMemoryStore();
    await s.set('k1', { a: 1 }, 1);
    const v = await s.get('k1');
    expect(v).toEqual({ a: 1 });
  });

  test('expires after ttl', async () => {
    const s = createMemoryStore();
    await s.set('k2', { b: 2 }, 0); // immediate expire
    const v = await s.get('k2');
    expect(v).toBeNull();
  });
});
