from types import SimpleNamespace
from uuid import uuid4

from app.flow_v2.executors.data_collection_executor import RuntimeV2DataCollectionExecutor


class Resolver:
    def resolve(self, *args, **kwargs):
        return SimpleNamespace(target_node_id=f"next-{kwargs['source_handle']}")


def runtime_input(text=None, message_id=None):
    return SimpleNamespace(
        metadata={}, message_text=text, input_message_id=message_id,
        message_id=None, event_id=None, webhook_id=None,
        external_user_id='5511999999999', conversation_id=None, contact_id=None,
    )


def session():
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4(), flow_version_id=uuid4(), context={}, variables={})


def test_invalid_answers_remain_in_same_node_until_limit_then_use_invalid_output():
    executor = RuntimeV2DataCollectionExecutor(event_store=None, transition_resolver=Resolver())
    current = session()
    node = {'id': 'collect-period', 'data': {'variable_name': 'preferred_period', 'data_type': 'email', 'auto_retry_invalid': True, 'max_attempts': 3, 'invalid_message': 'Tente novamente.'}}

    started = executor.execute(None, snapshot={}, session=current, node=node, runtime_input=runtime_input())
    assert started.status == 'wait' and started.next_node_id == 'collect-period'

    for attempt in (1, 2):
        result = executor.execute(None, snapshot={}, session=current, node=node, runtime_input=runtime_input('inválido', f'msg-{attempt}'))
        assert result.status == 'wait' and result.next_node_id == 'collect-period'
        assert current.context['attempts'] == attempt
        assert current.context['waiting_for_input'] is True
        assert current.context['current_node'] == 'collect-period'
        assert current.context['state'] == 'waiting_retry'

    exceeded = executor.execute(None, snapshot={}, session=current, node=node, runtime_input=runtime_input('inválido', 'msg-3'))
    assert exceeded.next_node_id == 'next-invalid'
    assert exceeded.next_source_handle == 'invalid'
    assert 'data_collection' not in current.context


def test_missing_auto_retry_flag_preserves_legacy_immediate_invalid_route():
    executor = RuntimeV2DataCollectionExecutor(event_store=None, transition_resolver=Resolver())
    current = session()
    node = {'id': 'legacy', 'data': {'variable_name': 'email', 'data_type': 'email', 'max_attempts': 3}}
    executor.execute(None, snapshot={}, session=current, node=node, runtime_input=runtime_input())
    result = executor.execute(None, snapshot={}, session=current, node=node, runtime_input=runtime_input('inválido', 'legacy-msg'))
    assert result.next_node_id == 'next-invalid'
    assert result.status == 'continue'


def test_end_behavior_finishes_without_following_invalid_edge():
    executor = RuntimeV2DataCollectionExecutor(event_store=None, transition_resolver=Resolver())
    current = session()
    node = {'id': 'collect', 'data': {'variable_name': 'email', 'data_type': 'email', 'auto_retry_invalid': True, 'max_attempts': 1, 'attempts_exceeded_behavior': 'end'}}
    executor.execute(None, snapshot={}, session=current, node=node, runtime_input=runtime_input())
    result = executor.execute(None, snapshot={}, session=current, node=node, runtime_input=runtime_input('inválido', 'last'))
    assert result.status == 'complete'
    assert result.next_node_id is None
