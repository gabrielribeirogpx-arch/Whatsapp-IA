import uuid
from unittest.mock import patch

from app.services.suitable_service import SuitableService, NOT_CONNECTED_MESSAGE, suitable_fingerprint


class FakeConnSvc:
    def __init__(self, key=None): self.key = key
    def get_active_connection(self, tenant_id, provider):
        if self.key is None: return None
        return type('C', (), {'auth_type':'api_key','api_key_encrypted':self.key})()


def service(key='secret'):
    s = SuitableService(object(), uuid.uuid4(), base_url='https://suitable.test')
    s.connection_service = FakeConnSvc(key)
    return s


def test_payload_converted_phone_total_payment_delivery():
    built, err = service().build_order_payload({'customer': {'name':'Ana','phone':'(16)99999-9999'}, 'order_type':'delivery', 'address': {'street':'A'}, 'delivery_fee':5, 'payment_methods':['cash'], 'products':[{'name':'Pizza','quantity':2,'unit_price':35}]})
    assert err is None
    assert built['order_id'] is None
    assert built['customer']['phone'] == '5516999999999'
    assert built['products_total'] == 70
    assert built['payment']['products_total'] == 70
    assert built['payment']['delivery_fee'] == 5
    assert built['payment']['paid'] is False
    assert built['payment']['generate_invoice'] is False


def test_phone_normalization_variants():
    assert SuitableService.normalize_phone('16999999999') == '5516999999999'
    assert SuitableService.normalize_phone('999999999') == '5516999999999'
    assert SuitableService.normalize_phone('+55 16 99999-9999') == '5516999999999'


def test_error_without_credential():
    assert service(None).check_key()['message'] == NOT_CONNECTED_MESSAGE


def test_validation_errors():
    s = service()
    base = {'customer': {'name':'Ana','phone':'16999999999'}, 'order_type':'delivery'}
    assert 'Endereço' in s.build_order_payload({**base, 'products':[{'name':'x','quantity':1,'unit_price':1}]})[1]
    assert 'ao menos 1 produto' in s.build_order_payload({**base, 'address':{}})[1]
    assert 'quantidade' in s.build_order_payload({**base, 'address':{}, 'products':[{'quantity':0,'unit_price':1}]})[1]
    assert 'preço unitário' in s.build_order_payload({**base, 'address':{}, 'products':[{'quantity':1,'unit_price':0}]})[1]


@patch('app.services.integration_connection_service.IntegrationConnectionService.decrypt_credential', return_value='secret')
@patch('requests.request')
def test_success_mocked_post_upsert(req, _dec):
    req.return_value.status_code = 200; req.return_value.content = b'{"id":"1"}'; req.return_value.json.return_value = {'id':'1'}
    out = service('encrypted').create_order(customer={'name':'Ana','phone':'16999999999'}, order_type='delivery', address={'street':'A'}, products=[{'quantity':1,'unit_price':2}], payment_methods=[])
    assert out['ok'] is True
    assert req.call_args.kwargs['json']['order_id'] is None
    assert req.call_args.args[:2] == ('POST', 'https://suitable.test/order/upsert/')


def test_fingerprint_stable_blocks_duplicates_basis():
    p1={'b':2,'a':1}; p2={'a':1,'b':2}
    assert suitable_fingerprint('suitable_create_order', p1) == suitable_fingerprint('suitable_create_order', p2)
