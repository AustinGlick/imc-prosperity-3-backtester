from prosperity3bt.datamodel import OrderDepth, TradingState, Order
import json

# ── constants ──────────────────────────────────────────────────────────────
EMERALDS = 'EMERALDS'
TOMATOES = 'TOMATOES'

POS_LIMITS = {EMERALDS: 80, TOMATOES: 80}


# ── base class ─────────────────────────────────────────────────────────────
class ProductTrader:
    """Handles all the repetitive setup so your strategy class stays clean."""

    def __init__(self, symbol, state, last_td, new_td):
        self.symbol = symbol
        self.state  = state
        self.last_td = last_td
        self.new_td  = new_td
        self.orders  = []

        # position
        self.pos_limit = POS_LIMITS.get(symbol, 0)
        self.position  = state.position.get(symbol, 0)
        self.max_buy   = self.pos_limit - self.position
        self.max_sell  = self.pos_limit + self.position

        # order book
        od = state.order_depths.get(symbol, OrderDepth())
        self.bids = {p: abs(v) for p, v in sorted(od.buy_orders.items(),  reverse=True)}
        self.asks = {p: abs(v) for p, v in sorted(od.sell_orders.items())}

        # price levels
        self.best_bid  = max(self.bids) if self.bids else None
        self.best_ask  = min(self.asks) if self.asks else None
        self.bid_wall  = min(self.bids) if self.bids else None
        self.ask_wall  = max(self.asks) if self.asks else None
        self.wall_mid  = (self.bid_wall + self.ask_wall) / 2 \
                         if self.bid_wall and self.ask_wall else None

    # ── order helpers ───────────────────────────────────────────────────────
    def buy(self, price, volume):
        vol = min(abs(int(volume)), self.max_buy)
        if vol > 0:
            self.orders.append(Order(self.symbol, int(price), vol))
            self.max_buy -= vol

    def sell(self, price, volume):
        vol = min(abs(int(volume)), self.max_sell)
        if vol > 0:
            self.orders.append(Order(self.symbol, int(price), -vol))
            self.max_sell -= vol

    # ── EMA helper ──────────────────────────────────────────────────────────
    def ema(self, key, window, value):
        prev = self.last_td.get(key, value)
        alpha = 2 / (window + 1)
        result = alpha * value + (1 - alpha) * prev
        self.new_td[key] = result
        return result

    def get_orders(self):
        return {}


# ── strategy: Emeralds ─────────────────────────────────────────────────────
# Stable true price — market make around wall_mid
class EmeraldsTrader(ProductTrader):

    def __init__(self, state, last_td, new_td):
        super().__init__(EMERALDS, state, last_td, new_td)

    def get_orders(self):
        if self.wall_mid is None:
            return {}

        # 1. take any profitable fills immediately
        for price, vol in self.asks.items():
            if price < self.wall_mid:
                self.buy(price, vol)

        for price, vol in self.bids.items():
            if price > self.wall_mid:
                self.sell(price, vol)

        # 2. passive quotes — overbid best bid, undercut best ask
        bid_price = self.bid_wall + 1
        ask_price = self.ask_wall - 1

        for price, vol in self.bids.items():
            if price < self.wall_mid:
                bid_price = price + 1
                break

        for price, vol in self.asks.items():
            if price > self.wall_mid:
                ask_price = price - 1
                break

        self.buy(bid_price,  self.max_buy)
        self.sell(ask_price, self.max_sell)

        return self.orders


# ── strategy: Tomatoes ─────────────────────────────────────────────────────
# Price drifts over time — wall_mid is still our best fair value estimate
class TomatoesTrader(ProductTrader):

    def __init__(self, state, last_td, new_td):
        super().__init__(TOMATOES, state, last_td, new_td)

    def get_orders(self):
        if self.wall_mid is None:
            return {}

        for price, vol in self.asks.items():
            if price < self.wall_mid:
                self.buy(price, vol)

        for price, vol in self.bids.items():
            if price > self.wall_mid:
                self.sell(price, vol)

        self.buy(self.bid_wall + 1,  self.max_buy)
        self.sell(self.ask_wall - 1, self.max_sell)

        return self.orders


# ── entry point ────────────────────────────────────────────────────────────
class Trader:

    def run(self, state: TradingState):

        try:
            last_td = json.loads(state.traderData) if state.traderData else {}
        except:
            last_td = {}

        new_td = {}
        result = {}

        traders = {
            EMERALDS: EmeraldsTrader,
            #TOMATOES: TomatoesTrader,
        }

        for symbol, TraderClass in traders.items():
            if symbol in state.order_depths:
                try:
                    t = TraderClass(state, last_td, new_td)
                    result[symbol] = t.get_orders()
                except Exception as e:
                    print(f"ERROR {symbol}: {e}")

        return result, 0, json.dumps(new_td)