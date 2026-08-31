from uuid import uuid4

from app.flow_v2.actions import SendMessageAction, is_message_delivery_action, is_non_empty_outbound_action


def test_empty_message_action_is_not_deliverable_or_message_sent():
    action = SendMessageAction(tenant_id=uuid4(), session_id=uuid4(), external_user_id='5511999999999', text='  ')
    assert is_non_empty_outbound_action(action) is False
    assert is_message_delivery_action(action) is False
