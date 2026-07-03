function idempotencyMiddleware(store, options = {}) {
  return async function (req, res, next) {
    try {
      const key = req.body && (req.body.idempotencyKey || req.headers['x-idempotency-key']);
      if (!key) return next();

      const prev = await store.get(key);
      if (prev) return res.json(prev);

      // wrap res.json to capture result
      const origJson = res.json.bind(res);
      res.json = async (body) => {
        try { await store.set(key, body, options.ttlSeconds || 24*3600); } catch (e) { /* ignore */ }
        return origJson(body);
      };
      next();
    } catch (e) { next(e); }
  };
}

module.exports = { idempotencyMiddleware };
