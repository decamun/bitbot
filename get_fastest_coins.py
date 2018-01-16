from bittrex.bittrex import Bittrex, API_V2_0, API_V1_1
from binance.client import Client
import json
import time
import numpy as np
import sys
from transitions import Machine, State
import requests
import time
import decimal

# get all the coins
url = 'https://www.cryptocompare.com/api/data/coinlist'
coin_info = requests.get(url)
coin_info = coin_info.json()

#get all the market information
match_coins = dict()
with open('api_key.json', 'r') as f:
    api_key = json.load(f)

binance = Client(api_key['binance_key'], api_key['binance_secret'])
bittrex = Bittrex(api_key['bittrex_key'], api_key['bittrex_secret'])

bin_markets = binance.get_products()
bit_markets = bittrex.get_currencies()

for bin_market in bin_markets['data']:
    for bit_market in bit_markets['result']:
        if bin_market['baseAsset'] == bit_market['Currency']:
            coin_id = bin_market['baseAsset']
            print 'Found Coin %s' % coin_id
            for coin in coin_info['Data']:
                if coin_info['Data'][coin]['Symbol'] == coin_id:

                    id = coin_info['Data'][coin]['Id']
                    url = 'https://www.cryptocompare.com/api/data/coinsnapshotfullbyid/?id=%s' % id
                    coin_detail = (requests.get(url)).json()

                    match_coins[coin_id] = dict()
                    match_coins[coin_id]['symbol'] = coin_id
                    match_coins[coin_id]['bin'] = dict()
                    match_coins[coin_id]['bit'] = dict()

                    match_coins[coin_id]['block_time'] = int(coin_detail['Data']['General']['BlockTime'])
                    match_coins[coin_id]['bit']['block_thresh'] = float(bit_market['MinConfirmation'])
                    match_coins[coin_id]['bin']['block_thresh'] = None
                    match_coins[coin_id]['bit']['tx_fee'] = float(bit_market['TxFee'])
                    match_coins[coin_id]['bin']['tx_fee'] = float(bin_market['withdrawFee'])
                    match_coins[coin_id]['bin']['decimals'] = bin_market['decimalPlaces']
                    match_coins[coin_id]['max_fee'] = match_coins[coin_id]['bit']['tx_fee'] if match_coins[coin_id]['bit']['tx_fee'] > match_coins[coin_id]['bin']['tx_fee'] else match_coins[coin_id]['bin']['tx_fee']
                    match_coins[coin_id]['bit']['rx_time'] = match_coins[coin_id]['block_time'] * match_coins[coin_id]['bit']['block_thresh']
                    print match_coins[coin_id]

sorted_by_rx_time = sorted(match_coins.iteritems(),
                           key=lambda (k, i): (i['bit']['rx_time'] if i['bit']['rx_time'] > 1 else 10000000000, k))
for coin in sorted_by_rx_time:
    print coin[1]['symbol']
    print coin[1]['bit']['rx_time']