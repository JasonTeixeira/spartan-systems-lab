import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '15s', target: 25 },
    { duration: '30s', target: 100 },
    { duration: '15s', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(99)<300'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

export default function () {
  const tenantId = (__VU % 3) + 1;
  const payload = JSON.stringify({
    tenant_id: tenantId,
    idempotency_key: `k6-${__VU}-${__ITER}`,
    event_type: 'api_call',
    units: 10,
    cost_usd: '0.002500',
    region: 'us-east-1',
    occurred_at: new Date().toISOString(),
  });

  const postRes = http.post(`${BASE_URL}/events`, payload, {
    headers: { 'Content-Type': 'application/json' },
  });
  check(postRes, { 'ingest 201': (r) => r.status === 201 });

  const getRes = http.get(`${BASE_URL}/tenants/${tenantId}/summary`);
  check(getRes, { 'summary 200': (r) => r.status === 200 });

  sleep(0.05);
}
