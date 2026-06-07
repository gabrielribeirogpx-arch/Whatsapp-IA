/**
 * BACKEND — Endpoints necessários para o PWA Mobile
 * ─────────────────────────────────────────────────
 * Estes endpoints precisam existir. Se já existem com nomes diferentes,
 * ajuste as chamadas nos hooks / MobileChatShell.
 *
 * NÃO alterar Runtime V2, Delay Worker, Condition, Action Engine,
 * SessionManager, WhatsApp Runtime, SSE Backend existente.
 */

// ══════════════════════════════════════════════════════════════
// 1. POST /api/push/subscribe
// Salva uma PushSubscription do browser no banco de dados.
// ══════════════════════════════════════════════════════════════
//
// Body (do browser): PushSubscription.toJSON() =
//   { endpoint: string, keys: { p256dh: string, auth: string } }
//
// Exemplo Next.js API Route:
//
// import { NextRequest, NextResponse } from 'next/server';
// import { db } from '@/lib/db';   // seu cliente de banco
//
// export async function POST(req: NextRequest) {
//   const body = await req.json();
//   const userId = req.headers.get('x-user-id');   // ou JWT
//
//   await db.push_subscriptions.upsert({
//     where:  { endpoint: body.endpoint },
//     update: { keys: body.keys, user_id: userId, active: true },
//     create: { endpoint: body.endpoint, keys: body.keys, user_id: userId, active: true },
//   });
//
//   return NextResponse.json({ ok: true });
// }

// ══════════════════════════════════════════════════════════════
// 2. POST /api/push/unsubscribe
// Desativa uma subscription no banco.
// ══════════════════════════════════════════════════════════════
//
// Body: { endpoint: string }
//
// export async function POST(req: NextRequest) {
//   const { endpoint } = await req.json();
//   await db.push_subscriptions.update({
//     where:  { endpoint },
//     data:   { active: false },
//   });
//   return NextResponse.json({ ok: true });
// }

// ══════════════════════════════════════════════════════════════
// 3. PATCH /api/conversations/:id/assign
// Atribui o usuário logado como responsável pela conversa.
// Dispara SSE event 'message_assigned' para todos os clientes.
// ══════════════════════════════════════════════════════════════
//
// Body: { self: true }  ou  { user_id: string }
//
// export async function PATCH(req: NextRequest, { params }: { params: { id: string } }) {
//   const userId  = req.headers.get('x-user-id');
//   const body    = await req.json();
//   const assignee = body.self ? userId : body.user_id;
//
//   const convo = await db.conversations.update({
//     where: { id: params.id },
//     data:  { assigned_user_id: assignee },
//   });
//
//   // Emitir SSE para todos os clientes conectados
//   sseEmitter.emit('message_assigned', {
//     conversation_id: params.id,
//     user_id:         assignee,
//     user_name:       req.headers.get('x-user-name') || 'Atendente',
//   });
//
//   return NextResponse.json(convo);
// }

// ══════════════════════════════════════════════════════════════
// 4. Envio de push ao cliente (server-side, disparado pelo backend)
// Usar a lib 'web-push' (npm install web-push)
// ══════════════════════════════════════════════════════════════
//
// import webpush from 'web-push';
//
// webpush.setVapidDetails(
//   'mailto:admin@seudominio.com',
//   process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY!,
//   process.env.VAPID_PRIVATE_KEY!,
// );
//
// async function sendPushToUser(userId: string, payload: object) {
//   const subs = await db.push_subscriptions.findMany({
//     where: { user_id: userId, active: true },
//   });
//
//   for (const sub of subs) {
//     try {
//       await webpush.sendNotification(
//         { endpoint: sub.endpoint, keys: sub.keys },
//         JSON.stringify(payload)
//       );
//     } catch (err: any) {
//       // 410 Gone = subscription expirada
//       if (err.statusCode === 410) {
//         await db.push_subscriptions.update({ where: { endpoint: sub.endpoint }, data: { active: false } });
//       }
//     }
//   }
// }
//
// // Chamar em handoff_requested, nova mensagem não lida, etc:
// await sendPushToUser(assignedUserId, {
//   title: 'Nova mensagem · Wazza',
//   body:  `${contactName}: ${messagePreview}`,
//   tag:   'wazza-message',
//   data:  { conversation_id: convoId, conversation_url: `/mobile/inbox` },
// });

// ══════════════════════════════════════════════════════════════
// VAPID keys (gerar uma única vez):
// npx web-push generate-vapid-keys
// Adicionar ao .env:
//   NEXT_PUBLIC_VAPID_PUBLIC_KEY=...
//   VAPID_PRIVATE_KEY=...
// ══════════════════════════════════════════════════════════════
