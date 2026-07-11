const request = require('supertest');
const { createApp } = require('../src/mockServer');

describe('Payment capability contract tests', () => {
  let app;

  beforeAll(() => {
    app = createApp();
  });

  test('idempotency_return_previous: same idempotencyKey returns previous result and not double charge', async () => {
    const payload = {
      requestId: 'r-1',
      idempotencyKey: 'idem-123',
      userId: 'user-1',
      amount: 10,
      currency: 'CNY'
    };

    const res1 = await request(app).post('/v1/payments/deduct').send(payload);
    expect(res1.statusCode).toBe(200);
    expect(res1.body.status).toBe('SUCCESS');

    const res2 = await request(app).post('/v1/payments/deduct').send(payload);
    expect(res2.statusCode).toBe(200);
    expect(res2.body.transactionId).toBe(res1.body.transactionId);

    const ledger = await request(app).get('/_internal/ledger');
    expect(Array.isArray(ledger.body)).toBe(true);
    expect(ledger.body.length).toBe(1);
  });

  test('insufficient_funds: returns INSUFFICIENT_FUNDS and does not retry', async () => {
    const payload = {
      requestId: 'r-2',
      idempotencyKey: 'idem-999',
      userId: 'user-2',
      amount: 1000,
      currency: 'CNY'
    };

    const res = await request(app).post('/v1/payments/deduct').send(payload);
    expect(res.statusCode).toBe(402);
    expect(res.body.code).toBe('INSUFFICIENT_FUNDS');
  });
});
