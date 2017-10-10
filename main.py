from bittrex import Bittrex
import json

def api_call(fn):
    resp = fn()
    assert resp['success']
    return resp['result']


with open('api_key.json','r') as f:
    api_key = json.load(f)

bittrex_api = Bittrex(api_key['key'], api_key['secret'])

markets = api_call(bittrex_api.get_markets)
