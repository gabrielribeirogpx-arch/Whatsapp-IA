import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const baseUrl = __ENV.BASE_URL || 'http://127.0.0.1:8000';
if (/railway\.app|wazza\.ai|production/i.test(baseUrl) && __ENV.ALLOW_PRODUCTION !== 'I_UNDERSTAND_THIS_IS_UNSAFE') {
  throw new Error('Refusing a production-like BASE_URL. Use an isolated environment.');
}

const scenario = __ENV.SCENARIO || 'distinct';
const duration = __ENV.DURATION || '30s';
const rate = Number(__ENV.RATE || 10);
export const options = {
  scenarios: {
    webhook: { executor: 'constant-arrival-rate', rate, timeUnit: '1s', duration, preAllocatedVUs: Math.max(10, rate), maxVUs: Math.max(20, rate * 2) },
  },
  thresholds: { http_req_failed: ['rate<0.01'], http_req_duration: ['p(95)<1000'] },
};
const accepted = new Counter('webhook_accepted');
const failures = new Rate('webhook_failures');
const latency = new Trend('webhook_latency', true);

function payload() {
  const sameConversation = scenario === 'same-conversation';
  const duplicate = scenario === 'duplicates';
  const suffix = sameConversation ? 'same' : `${__VU}-${__ITER}`;
  const messageId = duplicate ? 'wamid.load.duplicate' : `wamid.load.${suffix}`;
  return { object: 'whatsapp_business_account', entry: [{ changes: [{ value: {
    metadata: { phone_number_id: __ENV.PHONE_NUMBER_ID || 'test-phone-number-id' },
    contacts: [{ profile: { name: 'Load Test' }, wa_id: `55119999${suffix}` }],
    messages: [{ from: `55119999${suffix}`, id: messageId, timestamp: `${Math.floor(Date.now() / 1000)}`, type: 'text', text: { body: 'synthetic load test message' } }],
  } }] }] };
}

export default function () {
  const response = http.post(`${baseUrl}/webhook`, JSON.stringify(payload()), { headers: { 'Content-Type': 'application/json' }, tags: { scenario } });
  latency.add(response.timings.duration);
  const ok = check(response, { 'webhook acknowledged': r => r.status >= 200 && r.status < 300 });
  failures.add(!ok);
  if (ok) accepted.add(1);
  sleep(0.01);
}
