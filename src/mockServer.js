const express = require('express');
const bodyParser = require('body-parser');

function createApp() {
  const app = express();
  app.use(bodyParser.json());

  // In-memory stores for example
  const ledger = [];
  const users = new Map();
  users.set('user-1', { balance: 100 });

  // plug in idempotency store
  const { createMemoryStore } = require('../infra/idempotency');
  const { idempotencyMiddleware } = require('../infra/idempotency/middleware');
  const store = createMemoryStore();
  app.use(idempotencyMiddleware(store));

  app.post('/v1/payments/deduct', (req, res) => {
    const { idempotencyKey, userId, amount, requestId } = req.body || {};
    if (!idempotencyKey) return res.status(400).json({ error: 'missing idempotencyKey' });
    if (!userId) return res.status(400).json({ error: 'missing userId' });

    const user = users.get(userId) || { balance: 0 };
    if (amount > user.balance) {
      const result = { status: 'FAILED', transactionId: null, code: 'INSUFFICIENT_FUNDS', message: '余额不足' };
      // middleware will store result via res.json wrapper
      return res.status(402).json(result);
    }

    // perform deduction
    user.balance -= amount;
    users.set(userId, user);
    const transactionId = `tx-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
    const result = { status: 'SUCCESS', transactionId, message: '扣款成功' };
    ledger.push({ transactionId, userId, amount, requestId });
    return res.json(result);
  });

  // helper endpoints for tests
  app.get('/_internal/ledger', (req, res) => res.json(ledger));
  app.get('/_internal/users/:id', (req, res) => res.json(users.get(req.params.id) || {}));

  return app;
}

// If run directly, start the server
if (require.main === module) {
  const app = createApp();
  const port = process.env.PORT || 3000;
  app.listen(port, () => console.log(`Mock server listening on ${port}`));
}

module.exports = { createApp };
