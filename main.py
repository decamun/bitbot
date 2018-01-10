from bittrex import Bittrex
from binance.client import Client
import json
import time
import numpy as np
import sys
from transitions import Machine, State
import requests

def norm_diff(a, b):
    return 2 * (a - np.mean((a, b))) / np.mean((a, b))


class Market(object):
    def __init__(self, symbols=None):
        print('Setting Constants...')
        # fractional difference required to fire
        self.opportunity_thresh = 0.015
        # ratio of buying power to buy #TODO determine this dynamically based on confidence
        self.buy_ratio = 0.75
        # ratio of selling power to sell #TODO determine this dynamically based on confidence
        self.sell_ratio = 0.75
        # condition thresholds: used to insure market buy doesn't get out of control
        self.sell_condition_ratio = 0.995
        self.buy_condition_ratio = 1.05
        # maximum transfer time allowable for cash coins
        self.max_transfer_time = 120
        print('Initializing State Machine...')
        self.arbitrage_target = None
        self.partner = None
        self.price_spreads = dict()
        states = [
            State(name='not_connected', on_exit='set_partner'),
            State(name='waiting'),
            State(name='cash_balance'),
            State(name='buying', on_enter='buy_target'),
            State(name='selling', on_enter='sell_target'),
            State(name='transferring', on_enter='transfer_target')
        ]

        transitions = [
            {'trigger': 'buy', 'source': 'cash_balance', 'dest': 'buying'},
            {'trigger': 'sell', 'source': '*', 'dest': 'selling'},
            {'trigger': 'connect', 'source': 'not_connected', 'dest': 'waiting'},
            {'trigger': 'disconnect', 'source': '*', 'dest': 'not_connected'},
            {'trigger': 'have_cash', 'source': 'waiting', 'dest': 'cash_balance'},
            {'trigger': 'wait', 'source': '*', 'dest': 'waiting'},
            {'trigger': 'transfer', 'source': 'cash_balance', 'dest': 'transferring'}
        ]
        self.machine = Machine(self, states=states, transitions=transitions)
        self.disconnect()
        print('Setting Default Symbols...')
        self.trading_pairs = dict()
        #symbol: the symbol the market api uses for the trading pair
        #asset: the symbol for the 'asset' to be bought and sold
        #cash: the symbol for the 'cash' used to buy and sell and to be moved to other markets
        self.trading_pairs['XLM/BTC'] = {'symbol': 'BTC-XLM', 'asset': 'BTC', 'cash': 'XLM'}
        self.trading_pairs['XLM/ETH'] = {'symbol': 'ETH-XLM', 'asset': 'ETH', 'cash': 'XLM'}
        self.trading_pairs['XRP/BTC'] = {'symbol': 'BTC-XRP', 'asset': 'BTC', 'cash': 'XRP'}
        self.trading_pairs['XRP/ETH'] = {'symbol': 'ETH-XRP', 'asset': 'ETH', 'cash': 'XRP'}
        self.trading_pairs['NAV/BTC'] = {'symbol': 'BTC-NAV', 'asset': 'BTC', 'cash': 'NAV'}

        if symbols is not None:
            print('Setting Custom Symbols...')
            for symbol_id in symbols:
                self.trading_pairs[symbol_id]['symbol'] = symbols[symbol_id]
        print('Getting Prices...')
        self.prices = dict()
        self.update_prices()
        print('Setting Wallets...')
        self.wallets = dict()
        #symbol: symbol the market api uses for the currency. Should be same as wallet_id
        #is_cash: whether the currency is considered cash
        self.wallets['BTC'] = {'symbol': 'BTC', 'is_cash': False, 'cash_thresh': 0.00, 'asset_thresh': 0.01,
                               'cryptocompare_id': 1182, 'memo': None, 'address': None, 'block_thresh': 30}
        self.wallets['ETH'] = {'symbol': 'ETH', 'is_cash': False, 'cash_thresh': 0.00, 'asset_thresh': 0.01,
                               'cryptocompare_id': 7605, 'memo': None, 'address': None, 'block_thresh': 30}
        self.wallets['XRP'] = {'symbol': 'XRP', 'is_cash': True, 'cash_thresh': 5, 'asset_thresh': 0.00,
                               'cryptocompare_id': 5031, 'memo': None, 'address': None, 'block_thresh': 30}
        self.wallets['XLM'] = {'symbol': 'XLM', 'is_cash': True, 'cash_thresh': 5, 'asset_thresh': 0.00,
                               'cryptocompare_id': 4614, 'memo': None, 'address': None, 'block_thresh': 30}
        self.wallets['NAV'] = {'symbol': 'NAV', 'is_cash': True, 'cash_thresh': 5, 'asset_thresh': 0.00,
                               'cryptocompare_id': 4571, 'memo': None, 'address': None, 'block_thresh': 10}
        # self.update_cash_coins() #uncomment to check blocktimes

        self.set_deposit_addresses()
        # verify deposit addresses
        if not self.verify_deposit_addresses():
            print 'Check Deposit Addresses!'
            raise Exception()

        print('Getting Balances...')
        self.balances = dict()
        self.cash_balances = None
        self.update_balances()
        print('Done Initializing Market.\n_________________________________________________________________\n')

    def set_deposit_addresses(self):
        return

    def verify_deposit_address(self, symbol, address, memo = None):
        return False

    def verify_deposit_addresses(self):
        for wallet_id in self.wallets:
            print 'Verifying address: %s' % wallet_id
            memo = self.wallets[wallet_id]['memo']
            address = self.wallets[wallet_id]['address']
            if not self.verify_deposit_address(self.wallets[wallet_id]['symbol'], address, memo):
                print 'Failed'
                return False

        return True

    def check_if_cash(self, wallet_id, retry_count=0):
        try:
            url = 'https://www.cryptocompare.com/api/data/coinsnapshotfullbyid/?id=%i' % \
                  self.wallets[wallet_id]['cryptocompare_id']
            resp = (requests.get(url)).json()

            # make sure coin is correct
            got_symbol = resp['Data']['General']['Symbol']
            expected_symbol = self.wallets[wallet_id]['symbol']
            if got_symbol != expected_symbol:
                print 'got wrong symbol from cryptocompare. Expected %s got %s' % (expected_symbol, got_symbol)
                raise Exception()

            block_time = resp['Data']['General']['BlockTime']
            block_thresh = self.wallets[wallet_id]['block_thresh']
            print '%s block time: %f, est. confirmation time: %f' % (wallet_id, block_time, block_time * block_thresh)
            return block_time * block_thresh < self.max_transfer_time

        except Exception as detail:
            print 'Handling runtime error: %s' % detail
            if retry_count < 5:
                return self.check_if_cash(wallet_id, retry_count+1)
            else:
                return False

    def update_cash_coins(self):
        for wallet_id in self.wallets:
            is_cash = self.check_if_cash(wallet_id)
            self.wallets[wallet_id]['is_cash'] = is_cash

    def get_buy_amount(self, pair_id):
        amount = self.buy_ratio * self.balances[self.trading_pairs[pair_id]['cash']]
        return amount

    def get_sell_amount(self, pair_id):
        cash_value = self.prices[pair_id]
        amount = self.sell_ratio * self.balances[self.trading_pairs[pair_id]['asset']] / cash_value
        return amount

    def get_transfer_amount(self, pair_id):
        #TODO determine this amount smartly
        amount = self.balances[self.trading_pairs[pair_id]['cash']]
        return amount

    def buy_order(self, amount, pair_id):
        return

    def sell_order(self, amount, pair_id):
        return

    def transfer_order(self, amount, pair_id):
        return

    def set_partner(self, partner=None):
        if partner is None:
            self.disconnect()
        else:
            print('Connecting to partner...')
            self.partner = partner
            self.calculate_spreads()

    def is_target(self, symbol_id=None):
        return self.trading_pairs[symbol_id] is self.trading_pairs[self.arbitrage_target]

    def buy_target(self, pair_id):
        amount = self.get_buy_amount(pair_id)
        asset = self.trading_pairs[pair_id]['asset']
        cash = self.trading_pairs[pair_id]['cash']
        print 'Selling %f %s for %s' % (amount, cash, asset)
        self.sell_order(amount, pair_id) #these are switched because the market thinks
        # we are selling what we consider ourselves to be buying
        self.wait()

    def sell_target(self, pair_id):
        amount = self.get_sell_amount(pair_id)
        asset = self.trading_pairs[pair_id]['asset']
        cash = self.trading_pairs[pair_id]['cash']
        print 'Buying %f %s with %s' % (amount, cash, asset)
        self.buy_order(amount, pair_id) #these are switched because the market thinks
        # we are buying what we consider ourselves to be selling
        self.wait()

    def transfer_target(self, pair_id):
        cash = self.trading_pairs[pair_id]['cash']
        amount = self.get_transfer_amount(pair_id)
        print 'Transferring %f %s to partner' % (amount, cash)
        self.transfer_order(amount, pair_id)
        self.wait()


    def set_arbitrage_target(self, symbol_id=None):
        self.arbitrage_target = symbol_id

    def get_current_price(self, symbol):
        return 0

    def calculate_spreads(self):
        if self.partner is not None:
            pairs = dict()
            for symbol_id in self.prices:
                if symbol_id in self.partner.prices:
                    pairs[symbol_id] = norm_diff(self.prices[symbol_id], self.partner.prices[symbol_id])
            self.price_spreads = pairs
        else:
            self.price_spreads = None

    def fetch_prices(self, to_update):
        new_prices = dict()
        for symbol_id in to_update:
            new_prices[symbol_id] = self.get_current_price(self.trading_pairs[symbol_id]['symbol'])

        return new_prices

    def update_prices(self, to_update=None, retry_count=0):
        if to_update is None:
            to_update = self.trading_pairs
        try:
            new_prices = self.fetch_prices(to_update)
        except Exception as detail:
            print 'Handling runtime error: ', detail
            if retry_count < 5:
                self.update_prices(to_update=to_update, retry_count=retry_count+1)
                return
            else:
                return

        self.prices = new_prices

    def get_current_balance(self, symbol):
        return 0

    def fetch_balances(self, to_update = None):
        if to_update is None:
            to_update = self.wallets
        new_balances = dict()
        for wallet_id in to_update:
            new_balances[wallet_id] = self.get_current_balance(self.wallets[wallet_id]['symbol'])
        return new_balances

    def update_balances(self, to_update=None, retry_count = 0):
        if to_update is None:
            to_update = self.wallets
        try:
            new_balances = self.fetch_balances(to_update)
        except Exception as detail:
            print 'Handling runtime error: ', detail
            if retry_count < 5:
                self.update_balances(to_update=to_update, retry_count=retry_count+1)
                return
            else:
                return

        # detect cash balances and update state if necessary
        cash_balances = []
        have_cash = False
        for wallet_id in to_update:
            if self.wallets[wallet_id]['is_cash'] and wallet_id in self.balances.keys() and \
                    new_balances[wallet_id] > self.wallets[wallet_id]['cash_thresh']:
                cash_balances.append(wallet_id)
                have_cash = True

        self.balances = new_balances
        self.set_cash_balances(cash_balances)

        # update states
        if have_cash and self.is_waiting():
            self.have_cash()

        if self.is_cash_balance() and not have_cash:
            self.wait()

    def set_cash_balances(self, cash_balances=None):
        if cash_balances is None:
            self.cash_balances = None
            self.wait()
        else:
            self.cash_balances = cash_balances

    def get_price(self, symbol):
        return self.prices[symbol]

    def get_balance(self, symbol):
        return self.balances[symbol]

    def check_for_opportunities(self):
        best_opportunity = None
        best_spread = None
        type = None
        for symbol_id in self.price_spreads:
            if abs(self.price_spreads[symbol_id]) > self.opportunity_thresh \
                    and abs(self.price_spreads[symbol_id]) > best_spread:

                # check for cash necessary opportunities
                if self.is_cash_balance() and self.trading_pairs[symbol_id]['cash'] in self.cash_balances:
                    # buy opportunity
                    if self.price_spreads[symbol_id] > 0:
                        best_opportunity = symbol_id
                        best_spread = abs(self.price_spreads[symbol_id])
                        type = 'BUY'

                    # transfer opportunity
                    else:
                        best_opportunity = symbol_id
                        best_spread = abs(self.price_spreads[symbol_id])
                        type = 'TRANSFER'


                # check for transfer opportunities
                if (self.is_cash_balance() or self.is_waiting()) and self.price_spreads[symbol_id] < 0 \
                        and self.balances[self.trading_pairs[symbol_id]['asset']] \
                        > self.wallets[self.trading_pairs[symbol_id]['asset']]['asset_thresh']:
                    best_opportunity = symbol_id
                    best_spread = abs(self.price_spreads[symbol_id])
                    type = 'SELL'

        #handle best opportunity
        if best_opportunity is not None:
            print 'Opportunity Found: Symbol %s, Type %s' % (best_opportunity, type)
            if type=='BUY':
                self.buy(best_opportunity)
            elif type == 'SELL':
                self.sell(best_opportunity)
            else: #type == 'TRANSFER'
                self.transfer(best_opportunity)
        else:
            print('None')


class BinanceMarket(Market):
    def __init__(self, key, secret):
        print('Binance Market Initializing...')
        self.client = Client(key, secret)
        symbols = dict()
        symbols['XLM/BTC'] = 'XLMBTC'
        symbols['XLM/ETH'] = 'XLMETH'
        symbols['XRP/BTC'] = 'XRPBTC'
        symbols['XRP/ETH'] = 'XRPETH'
        symbols['NAV/BTC'] = 'NAVBTC'
        Market.__init__(self, symbols)

    def verify_deposit_address(self, wallet_id, address, memo = None):
        resp = self.client.get_deposit_address(asset=wallet_id)
        if resp['success']:
            self.wallets[wallet_id]['address'] = str(resp['address'])
            self.wallets[wallet_id]['memo'] = str(resp['addressTag'])
            print 'address: %s, memo %s' % (str(resp['address']), str(resp['addressTag']))
            return True
        else:
            return False


    def fetch_prices(self, to_update):
        new_prices = dict()
        symbols = [self.trading_pairs[p]['symbol'] for p in self.trading_pairs]
        tickers = self.client.get_symbol_ticker()
        for ticker in tickers:
            for pair in self.trading_pairs:
                if self.trading_pairs[pair]['symbol'] == ticker['symbol']:
                    new_prices[pair] = float(ticker['price'])

        return new_prices

    def fetch_balances(self, to_update=None):
        if to_update is None:
            to_update = self.wallets

        account_info = self.client.get_account()
        balances = account_info['balances']
        new_balances = dict()
        for balance in balances:
            for wallet_id in self.wallets:
                if balance['asset'] == self.wallets[wallet_id]['symbol']:
                    new_balances[wallet_id] = float(balance['free'])

        return new_balances

    def buy_order(self, amount, pair_id):
        symbol = self.trading_pairs[pair_id]['symbol']
        return
        resp = self.client.order_market_buy(symbol=symbol, quantity=amount)

    def sell_order(self, amount, pair_id):
        symbol = self.trading_pairs[pair_id]['symbol']
        return
        resp = self.client.order_market_sell(symbol=symbol, quantity=amount)


    def transfer_order(self, amount, pair_id):
        symbol = self.trading_pairs[pair_id]['cash']
        address = self.partner.wallets[symbol]['address']
        memo = self.partner.wallets[symbol]['memo']

        print 'Transfer Order: %s %s %s' % (symbol, address, memo)
        return
        resp = self.client.withdraw(asset=symbol, address=address, addressTag=memo, amount=amount)

class BittrexMarket(Market):
    def __init__(self, key, secret):
        print('Bittrex Market Initializing...')
        self.api = Bittrex(key, secret)
        Market.__init__(self)

    def set_deposit_addresses(self):
        self.wallets['BTC']['address'] = '1FDjeNznNVaTKmvEKCe3HtD5f8mwBycLMw'
        self.wallets['ETH']['address'] = '0x838bc7b7fcff28b0a64007e6ff231215b8a0abef'
        self.wallets['NAV']['address'] = 'NRfGwZhNQiRe2aUwa2nH3xHjYXjT4jcfZQ'
        self.wallets['XRP']['address'] = 'rPVMhWBsfF9iMXYj3aAzJVkPDTFNSyWdKy'
        self.wallets['XRP']['memo'] = '1166176187'
        self.wallets['XLM']['address'] = 'GB6YPGW5JFMMP2QB2USQ33EUWTXVL4ZT5ITUNCY3YKVWOJPP57CANOF3'
        self.wallets['XLM']['memo'] = 'df33d069d9194f00bb7'

    def verify_deposit_address(self, symbol, address, memo = None):
        resp = self.api.get_deposit_address(symbol)
        if resp['success']:
            arg = resp['result']['Address']
            print 'expected: %s or %s, got: %s' % (address, memo, arg)
            return arg == address or arg == memo
        else:
            return False

    def fetch_prices(self, to_update):
        new_prices = dict()
        resp = self.api.get_market_summaries()
        if resp['success']:
            for market in resp['result']:
                for pair in self.trading_pairs:
                    if market['MarketName'] == self.trading_pairs[pair]['symbol']:
                        new_prices[pair] = market['Last']
            return new_prices
        else:
            raise Exception(message='Bittrex market_summaries api failure')

    def fetch_balances(self, to_update = None):
        if to_update is None:
            to_update = self.wallets
        symbols = [self.wallets[w]['symbol'] for w in to_update]
        new_balances = dict()
        resp = self.api.get_balances()
        if resp['success']:
            for balance in resp['result']:
                if str(balance['Currency']) in symbols:
                    new_balances[str(balance['Currency'])] = balance['Available']

            return new_balances
        else:
            return self.balances

    def buy_order(self, amount, pair_id):
        return
        #TODO be VERY careful if you uncomment this because you will start moving real money
        resp = self.api.trade_buy(market=self.trading_pairs[pair_id]['symbol'], order_type='MARKET', quantity=amount,
                                  time_in_effect='IMMEDIATE_OR_CANCEL', condition_type='LESS_THAN',
                                  target=self.buy_condition_ratio * self.prices[pair_id])

    def sell_order(self, amount, pair_id):
        return
        #TODO be VERY careful if you uncomment this because you will start moving real money
        resp = self.api.trade_sell(market=self.trading_pairs[pair_id]['symbol'], order_type='MARKET', quantity=amount,
                                   time_in_effect='IMMEDIATE_OR_CANCEL',
                                   condition_type='LESS_THAN', target=self.sell_condition_ratio * self.prices[pair_id])

    def transfer_order(self, amount, pair_id):
        symbol = self.trading_pairs[pair_id]['cash']
        address = self.partner.wallets[symbol]['address']
        memo = self.partner.wallets[symbol]['memo']

        print 'Transfer Order: %s %s %s' % (symbol, address, memo)
        return
        resp = self.api._api_query(path_dict={
            API_V1_1: '/account/withdraw',
            API_V2_0: '/key/balance/withdrawcurrency'
        }, options={'currency': symbol, 'quantity': amount, 'address': address, 'paymentid': memo}, protection=PROTECTION_PRV)


# load api keys
with open('api_key.json', 'r') as f:
    api_key = json.load(f)

# open a connection to binance
binance_market = BinanceMarket(api_key['binance_key'], api_key['binance_secret'])

# open connection to bittrex
bittrex_market = BittrexMarket(api_key['bittrex_key'], api_key['bittrex_secret'])

# connect the markets
print('Connecting Markets...')
bittrex_market.connect(binance_market)
binance_market.connect(bittrex_market)

print('Entering Loop...')
while 1:  # go forever
    # get balances
    print('Getting Balances...')
    bittrex_market.update_balances()
    binance_market.update_balances()
    #get prices
    print('Getting Prices...')
    binance_market.update_prices()
    bittrex_market.update_prices()
    # get spreads
    print('Getting Spreads...')
    bittrex_market.calculate_spreads()
    binance_market.calculate_spreads()

    # print('Bittrex Balances:')
    # print(bittrex_market.balances)
    # print(bittrex_market.cash_balances)
    # print('Binance Balances:')
    # print(binance_market.balances)
    # print(binance_market.cash_balances)
    # print('Bittrex Prices:')
    # print(bittrex_market.prices)
    # print('Binance Prices:')
    # print(binance_market.prices)

    # get opportunities
    print('Getting Opportunities...')
    print('Bittrex... State: %s, Balances: %s, Prices: %s, Spreads: %s' % (bittrex_market.state, str(bittrex_market.balances), str(bittrex_market.prices), str(bittrex_market.price_spreads)))
    bittrex_market.check_for_opportunities()
    print('Binance... State: %s, Balances: %s, Prices: %s, Spreads: %s' % (binance_market.state, str(binance_market.balances), str(binance_market.prices), str(binance_market.price_spreads)))
    binance_market.check_for_opportunities()