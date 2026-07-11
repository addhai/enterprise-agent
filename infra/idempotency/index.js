class MemoryStore {
  constructor() {
    this.map = new Map(); // key -> { value, expiresAt }
  }

  async get(key) {
    const entry = this.map.get(key);
    if (!entry) return null;
    if (entry.expiresAt && Date.now() >= entry.expiresAt) {
      this.map.delete(key);
      return null;
    }
    return entry.value;
  }

  async set(key, value, ttlSeconds) {
    let expiresAt = null;
    if (typeof ttlSeconds === 'number') {
      if (ttlSeconds <= 0) expiresAt = Date.now();
      else expiresAt = Date.now() + ttlSeconds*1000;
    }
    this.map.set(key, { value, expiresAt });
  }

  async delete(key) {
    this.map.delete(key);
  }
}

function createMemoryStore() { return new MemoryStore(); }

module.exports = { createMemoryStore };
