"""Native Runtime V2 executor for ``data_collection``."""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5
from app.flow_v2.actions import ScheduleDelayAction, SendChoiceButtonsAction, SendMessageAction
from app.flow_v2.data_collection import validate_data_collection
from app.flow_v2.executors._legacy import BaseNodeExecutor, NodeExecutionResult
logger = logging.getLogger(__name__)

class RuntimeV2DataCollectionExecutor(BaseNodeExecutor):
    """Persist a wait checkpoint, consume one inbound value, and select a canonical handle."""
    def _next(self, db, snapshot, session, node_id, handle):
        return self.transition_resolver.resolve(db, snapshot=snapshot, session=session, source_node_id=node_id, source_handle=handle).target_node_id

    def execute(self, db, *, snapshot, session, node, runtime_input):
        node_id, data = str(node['id']), self._node_data(node)
        context = dict(session.context or {})
        waiting = context.get('data_collection') if context.get('waiting_for') == 'data_collection' and context.get('waiting_node_id') == node_id else None
        now = datetime.now(timezone.utc)
        if not isinstance(waiting, dict):
            seconds = max(0, int(data.get('timeout_seconds') or 0)); timeout_at = now + timedelta(seconds=seconds) if seconds else None
            retry_mode = data.get('auto_retry_invalid') is True
            waiting = {'variable_name': data.get('variable_name'), 'data_type': data.get('data_type'), 'attempts': 0, 'max_attempts': max(1, int(data.get('max_attempts') or 1)), 'timeout_at': timeout_at.isoformat() if timeout_at else None, 'node_id': node_id, 'processed_message_ids': [], 'retry_mode': retry_mode, 'state': 'waiting_input'}
            context.update({'waiting_for': 'data_collection', 'waiting_node_id': node_id, 'data_collection': waiting, 'attempts': 0, 'waiting_for_input': True, 'current_node': node_id, 'variable_name': data.get('variable_name'), 'retry_mode': retry_mode, 'state': 'waiting_input'}); session.context = context
            actions = []
            options = [o for o in data.get('options', []) if isinstance(o, dict) and o.get('id') and o.get('label')]
            if data.get('data_type') == 'choice' and options and data.get('display_mode', 'buttons') != 'text':
                mode = 'buttons' if data.get('display_mode', 'buttons') == 'buttons' and len(options) <= 3 else 'list'
                buttons = tuple({'type': 'reply', 'reply': {'id': str(o['id']), 'title': str(o['label'])[:20]}} for o in options[:3])
                sections = ({'title': 'Opções', 'rows': [{'id': str(o['id']), 'title': str(o['label'])[:24]} for o in options[:10]]},)
                actions.append(SendChoiceButtonsAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=str(data.get('prompt') or data.get('label') or 'Escolha uma opção'), node_id=node_id, options=tuple({'id': str(o['id']), 'label': str(o['label'])} for o in options), buttons=buttons, sections=sections, display_mode=mode, metadata={'node_type': 'data_collection'}))
            if timeout_at:
                key = f'data_collection_timeout:{session.id}:{node_id}'
                actions.append(ScheduleDelayAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, job_id=uuid5(NAMESPACE_URL, key), resume_node_id=node_id, run_at=timeout_at, seconds=seconds, metadata={'event_type': 'data_collection_timeout', 'idempotency_key': key, 'node_id': node_id}))
            logger.info('event=data_collection_wait_started tenant_id=%s flow_version_id=%s session_id=%s node_id=%s variable_name=%s data_type=%s result=wait', session.tenant_id, session.flow_version_id, session.id, node_id, data.get('variable_name'), data.get('data_type'))
            return NodeExecutionResult(actions=tuple(actions), status='wait', next_node_id=node_id)
        if runtime_input.metadata.get('event_type') == 'data_collection_timeout':
            return self._finish(db, snapshot, session, context, node_id, data, 'timeout', 'data_collection_timeout', runtime_input)
        key = str(runtime_input.input_message_id or runtime_input.message_id or runtime_input.event_id or runtime_input.webhook_id or '')
        processed = list(waiting.get('processed_message_ids') or [])
        if key and key in processed: return NodeExecutionResult(status='wait', next_node_id=node_id)
        if key: processed.append(key)
        waiting['processed_message_ids'] = processed[-50:]
        raw = runtime_input.message_text
        logger.info('event=data_collection_input_received session_id=%s node_id=%s variable_name=%s data_type=%s attempt=%s', session.id, node_id, data.get('variable_name'), data.get('data_type'), waiting.get('attempts', 0))
        cancel = {str(w).strip().casefold() for w in data.get('cancel_keywords', []) if str(w).strip()}
        if str(raw or '').strip().casefold() in cancel:
            return self._finish(db, snapshot, session, context, node_id, data, 'cancel', 'data_collection_cancelled', runtime_input)
        result = validate_data_collection(data, raw, runtime_input.metadata)
        if not result.valid:
            waiting['attempts'] = int(waiting.get('attempts') or 0) + 1
            auto_retry = waiting.get('retry_mode') is True
            waiting['state'] = 'waiting_retry' if auto_retry else 'invalid'
            context.update({'data_collection': waiting, 'attempts': waiting['attempts'], 'waiting_for_input': auto_retry, 'current_node': node_id, 'variable_name': data.get('variable_name'), 'retry_mode': auto_retry, 'state': waiting['state']}); session.context = context
            logger.info('event=data_collection_validation_failed session_id=%s node_id=%s attempt=%s result=invalid', session.id, node_id, waiting['attempts'])
            action = SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=str(data.get('invalid_message') or 'Valor inválido.\nTente novamente.'), metadata={'node_type': 'data_collection', 'attempt': waiting['attempts'], 'retry': auto_retry})
            if auto_retry and waiting['attempts'] < int(waiting['max_attempts']): return NodeExecutionResult(actions=(action,), status='wait', next_node_id=node_id)
            if auto_retry and data.get('attempts_exceeded_behavior') == 'end':
                self._clear_wait(context, session)
                return NodeExecutionResult(actions=(action,), status='complete', next_source_handle='invalid')
            finished = self._finish(db, snapshot, session, context, node_id, data, 'invalid', 'data_collection_completed', runtime_input)
            return NodeExecutionResult(actions=(action, *finished.actions), status=finished.status, next_node_id=finished.next_node_id, next_source_handle='invalid')
        name = str(data.get('variable_name') or ''); variables = dict(session.variables or {}); variables[name] = result.normalized_value; session.variables = variables
        metadata = dict(context.get('variable_metadata') or {}); metadata[name] = {'raw_value': result.raw_value, 'normalized_value': result.normalized_value, 'data_type': data.get('data_type'), 'collected_at': now.isoformat(), 'node_id': node_id}; context['variable_metadata'] = metadata
        if data.get('save_to_contact') and runtime_input.contact_id:
            from app.models.contact import Contact
            contact = db.get(Contact, runtime_input.contact_id)
            if contact and contact.tenant_id == session.tenant_id:
                fields = dict(contact.custom_fields_json or {}); fields[name] = result.normalized_value; contact.custom_fields_json = fields
        if data.get('save_to_lead'):
            fields = dict(context.get('lead_custom_fields') or {}); fields[name] = result.normalized_value; context['lead_custom_fields'] = fields
        logger.info('event=data_collection_value_saved session_id=%s node_id=%s variable_name=%s data_type=%s result=saved', session.id, node_id, name, data.get('data_type'))
        return self._finish(db, snapshot, session, context, node_id, data, 'success', 'data_collection_completed', runtime_input)

    def _finish(self, db, snapshot, session, context, node_id, data, handle, event, runtime_input):
        self._clear_wait(context, session)
        if handle != 'success' and not self._has_edge(snapshot, node_id, handle):
            return self.executeDefaultBehavior(handle, session=session, data=data, runtime_input=runtime_input)
        target = self._next(db, snapshot, session, node_id, handle)
        logger.info('event=%s tenant_id=%s flow_version_id=%s session_id=%s node_id=%s variable_name=%s data_type=%s result=%s next_node_id=%s', event, session.tenant_id, session.flow_version_id, session.id, node_id, data.get('variable_name'), data.get('data_type'), handle, target)
        return NodeExecutionResult(next_node_id=target, next_source_handle=handle)

    def _has_edge(self, snapshot, node_id, handle):
        """Check optional output presence without asking the resolver to emit an error."""
        snapshot_transitions = getattr(self.transition_resolver, '_snapshot_transitions', None)
        transition_matches = getattr(self.transition_resolver, '_matches', None)
        if not snapshot_transitions or not transition_matches:
            # Test/custom resolvers traditionally own the complete routing contract.
            return True
        transitions = snapshot_transitions(snapshot)
        return bool(transition_matches(transitions=transitions, source_node_id=node_id, source_handle=handle))

    def executeDefaultBehavior(self, event, *, session, data, runtime_input):
        """Execute the workspace/node fallback for an unconnected optional output."""
        canonical_event = 'retry_exhausted' if event == 'invalid' else event
        context = dict(session.context or {})
        workspace_policies = context.get('data_collection_default_behaviors') or {}
        node_policies = data.get('default_behaviors') or {}
        policy = node_policies.get(canonical_event) or workspace_policies.get(canonical_event) or {}
        message = policy.get('message') if isinstance(policy, dict) else None
        if canonical_event == 'timeout' and not message:
            message = 'O tempo para responder terminou. Este atendimento será encerrado.'
        actions = ()
        if message:
            actions = (SendMessageAction(
                tenant_id=session.tenant_id, session_id=session.id,
                external_user_id=runtime_input.external_user_id,
                conversation_id=runtime_input.conversation_id,
                contact_id=runtime_input.contact_id, text=str(message),
                metadata={'node_type': 'data_collection', 'default_behavior': canonical_event},
            ),)
        context['data_collection_default_behavior'] = canonical_event
        session.context = context
        logger.info('event=data_collection_default_behavior session_id=%s result=%s', session.id, canonical_event)
        return NodeExecutionResult(actions=actions, status='complete', next_source_handle=event)

    @staticmethod
    def _clear_wait(context, session):
        for key in ('waiting_for', 'waiting_node_id', 'data_collection', 'attempts', 'waiting_for_input', 'current_node', 'variable_name', 'retry_mode', 'state'):
            context.pop(key, None)
        session.context = context
