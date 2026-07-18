const assert = require('assert');
const fs = require('fs');
const path = require('path');

const componentPath = path.join(
  __dirname,
  '..',
  'components',
  'settings',
  'whatsapp-business',
  'reports',
  'CampaignTimelineChartClient.tsx',
);
const parentPath = path.join(
  __dirname,
  '..',
  'components',
  'settings',
  'whatsapp-business',
  'reports',
  'CampaignReportsPage.tsx',
);

const component = fs.readFileSync(componentPath, 'utf8');
const parent = fs.readFileSync(parentPath, 'utf8');

assert(component.startsWith('"use client";'), 'timeline chart must be client-only');
assert(component.includes('from "recharts"'), 'timeline chart must import Recharts directly');
assert(component.includes('ResponsiveContainer'), 'ResponsiveContainer must be rendered by isolated chart');
assert(component.includes('ComposedChart'), 'ComposedChart must be rendered by isolated chart');
assert(component.includes('Area'), 'Area must provide gradient fills for timeline series');
assert(component.includes('svg.recharts-surface'), 'diagnostics must check the Recharts SVG surface');
assert(component.includes('.recharts-responsive-container'), 'diagnostics must check the responsive container');
assert(component.includes('isAnimationActive={false}'), 'line animation must stay disabled for diagnostics');
assert(!parent.includes('loadRechartsComponent("Line")'), 'Line must not be dynamically imported individually');
assert(!parent.includes('loadRechartsComponent("LineChart")'), 'LineChart must not be dynamically imported individually');
assert(!parent.includes('loadRechartsComponent("ComposedChart")'), 'ComposedChart must not be dynamically imported individually');
assert(parent.includes('() => import("./CampaignTimelineChartClient")'), 'parent must dynamically import the complete chart');
assert(parent.includes('Não foi possível carregar o gráfico.'), 'chart errors must show a visible fallback');
assert(parent.includes('Tentar novamente'), 'chart fallback must expose retry action');

const fixedData = [
  { bucket: '01/07', sent: 100, delivered: 95, read: 70, failed: 5 },
  { bucket: '02/07', sent: 140, delivered: 132, read: 91, failed: 8 },
];
assert.strictEqual(fixedData.length, 2);
assert(fixedData.every((point) => ['sent', 'delivered', 'read', 'failed'].every((key) => Number.isFinite(point[key]))));
