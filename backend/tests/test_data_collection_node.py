from app.flow_v2.data_collection import validate_data_collection
from app.flow_v2.node_executors import EXECUTOR_REGISTRY


def valid(kind, value, **data):
    return validate_data_collection({'data_type': kind, 'required': True, 'normalize_value': True, **data}, value)


def test_native_executor_registered():
    assert EXECUTOR_REGISTRY['data_collection'].__name__ == 'RuntimeV2DataCollectionExecutor'


def test_text_required_and_lengths():
    assert valid('text', '  Olá  ').normalized_value == 'Olá'
    assert not valid('text', ' ', min_length=1).valid


def test_numbers_and_currency():
    assert valid('number', '100,50').normalized_value == 100.5
    result = valid('currency', 'R$ 1.100,50')
    assert result.normalized_value == 1100.5 and result.raw_value == 'R$ 1.100,50'


def test_email_phone_url_date_and_time():
    assert valid('email', 'USER@Example.com').normalized_value == 'user@example.com'
    assert not valid('email', 'invalid@').valid
    assert valid('phone', '+55 (11) 99999-9999').normalized_value == '+5511999999999'
    assert valid('url', 'example.com/path').normalized_value == 'https://example.com/path'
    assert valid('date', '28-07-2026').normalized_value == '2026-07-28'
    assert valid('time', '09:05').normalized_value == '09:05'


def test_cpf_cnpj_boolean():
    assert valid('cpf', '529.982.247-25').normalized_value == '52998224725'
    assert valid('cnpj', '04.252.011/0001-10').normalized_value == '04252011000110'
    assert valid('boolean', 'não').normalized_value is False


def test_choice_prefers_stable_interactive_id_and_custom_text_is_exact():
    data = {'options': [{'id': 'morning', 'label': 'Manhã', 'value': 'manha'}]}
    assert valid('choice', '', required=False, **data).valid  # optional empty
    result = validate_data_collection({'data_type': 'choice', **data}, 'ignored', {'selected_row_id': 'morning'})
    assert result.valid and result.normalized_value == 'manha'
    assert validate_data_collection({'data_type': 'choice', 'allow_custom_value': True, **data}, 'Manhã').normalized_value == 'manha'
    assert not validate_data_collection({'data_type': 'choice', **data}, 'manha').valid
