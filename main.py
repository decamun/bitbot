from bittrex import Bittrex
from binance.client import Client
import json
import requests

def api_call(fn):
    resp = fn()
    assert resp['success']
    return resp['result']

def scrape_bittrex(filename='market_histories_bittrex.json', interval='hour'):
    # TODO convert to just scrape btc/eth/etc/xrp
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


def scrape_binance(filename='market_histories_binance.json', interval='hour'):
    #TODO convert to just scrape btc/eth/etc/xrp and used binance api
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

#load api keys
with open('api_key.json','r') as f:
    api_key = json.load(f)

#open a connection to binance
binance_client = Client(api_key['binance_key'], api_key['binance_secret'])


#open connection to bittrex
bittrex_api = Bittrex(api_key['bittrex_key'], api_key['bittrex_secret'])

#things to do...
prices = binance_client.get_all_tickers()
print(prices)
