from bittrex import Bittrex
import json
import requests

def api_call(fn):
    resp = fn()
    assert resp['success']
    return resp['result']

def scrape(filename='market_histories.json', interval='hour'):
    #check the markets
    markets = api_call(bittrex_api.get_markets)

    #scrape market histories for all markets
    market_histories = dict()
    for market in markets:
        MarketName = market["MarketName"]
        print(MarketName)
        url = "https://bittrex.com/Api/v2.0/pub/market/GetTicks?marketName=%s&tickInterval=%s"%(MarketName, interval)
        market_histories[MarketName] = api_call(requests.get(url).json)
        print('...done')

    print("saving data to %s"%filename)
    with open(filename, 'w') as f:
        json.dump(market_histories, f, indent=1)


#open connection to bittrex
with open('api_key.json','r') as f:
    api_key = json.load(f)
bittrex_api = Bittrex(api_key['key'], api_key['secret'])

#scrape
scrape()
