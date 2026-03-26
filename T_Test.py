from prosperity3bt.datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Tuple
import json
import math

EMERALDS = "EMERALDS"
TOMATOES = "TOMATOES"

POS_LIMITS = {
    EMERALDS: 80,
    TOMATOES: 80,
}


class ProductTrader:
    def __init__(self, symbol, state, last_td, new_td):
        self.symbol = symbol
        self.state = state
        self.last_td = last_td
        self.new_td = new_td
        self.orders: List[Order] = []

        self.pos_limit = POS_LIMITS.get(symbol, 0)
        self.position = state.position.get(symbol, 0)
        self.max_buy = max(0, self.pos_limit - self.position)
        self.max_sell = max(0, self.pos_limit + self.position)

        od = state.order_depths.get(symbol, OrderDepth())
        self.bids = dict(sorted({p: abs(v) for p, v in od.buy_orders.items()}.items(), reverse=True))
        self.asks = dict(sorted({p: abs(v) for p, v in od.sell_orders.items()}.items()))

        self.best_bid = max(self.bids) if self.bids else None
        self.best_ask = min(self.asks) if self.asks else None

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

    def ema(self, key, window, value):
        prev = self.last_td.get(key, value)
        alpha = 2 / (window + 1)
        result = alpha * value + (1 - alpha) * prev
        self.new_td[key] = result
        return result

    def mid_price(self):
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2
        if self.best_bid is not None:
            return float(self.best_bid)
        if self.best_ask is not None:
            return float(self.best_ask)
        return None

    def imbalance_l1(self):
        if not self.bids or not self.asks:
            return 0.0
        bid_vol = abs(next(iter(self.bids.values())))
        ask_vol = abs(next(iter(self.asks.values())))
        denom = bid_vol + ask_vol
        if denom == 0:
            return 0.0
        return (bid_vol - ask_vol) / denom

    def get_orders(self):
        return []


class EmeraldsTrader(ProductTrader):
    """
    More stable product: quote around a fair value estimate and take obvious mispricings.
    """

    def __init__(self, state, last_td, new_td):
        super().__init__(EMERALDS, state, last_td, new_td)

    def get_orders(self):
        mid = self.mid_price()
        if mid is None:
            return []

        fair = self.ema("emeralds_fair", 25, mid)
        fair_int = int(round(fair))

        # Aggressively take obvious edge
        for price, vol in self.asks.items():
            if price <= fair_int - 1 and self.max_buy > 0:
                self.buy(price, vol)

        for price, vol in self.bids.items():
            if price >= fair_int + 1 and self.max_sell > 0:
                self.sell(price, vol)

        # Passive market making around fair value
        if self.best_bid is not None and self.best_ask is not None:
            bid_px = min(self.best_bid + 1, fair_int - 1)
            ask_px = max(self.best_ask - 1, fair_int + 1)

            if bid_px < ask_px:
                if self.position > 20:
                    self.sell(ask_px, min(8, self.max_sell))
                elif self.position < -20:
                    self.buy(bid_px, min(8, self.max_buy))
                else:
                    self.buy(bid_px, min(10, self.max_buy))
                    self.sell(ask_px, min(10, self.max_sell))

        return self.orders


class TomatoesTrader(ProductTrader):
    """
    Mean-reverting product:
    - Uses EMA fair value
    - Adds a small imbalance tilt
    - Trades only when edge is bigger than a few ticks
    - Quotes conservatively to avoid overtrading
    """

    def __init__(self, state, last_td, new_td):
        super().__init__(TOMATOES, state, last_td, new_td)

    def get_orders(self):
        mid = self.mid_price()
        if mid is None:
            return []

        # Slow-ish EMA because your analysis suggests mean reversion with a long half-life.
        ema_mid = self.ema("tomatoes_ema_mid", 60, mid)

        # Small imbalance adjustment:
        # positive imbalance tends to slightly support future price, so tilt fair value up a little.
        imb = self.imbalance_l1()
        fair = ema_mid + 12.0 * imb
        fair_int = int(round(fair))

        # Edge threshold:
        # larger than 1 tick to avoid paying spread for weak signals.
        edge = 2

        # Take clear mispricings
        for price, vol in self.asks.items():
            if self.max_buy <= 0:
                break
            if price <= fair_int - edge:
                self.buy(price, vol)

        for price, vol in self.bids.items():
            if self.max_sell <= 0:
                break
            if price >= fair_int + edge:
                self.sell(price, vol)

        # Inventory skew:
        # if long, lean sell quotes higher and reduce bid aggressiveness
        # if short, lean buy quotes higher and reduce ask aggressiveness
        inv_ratio = self.position / self.pos_limit if self.pos_limit else 0.0
        skew = int(round(inv_ratio * 2))

        # Passive quotes only if there is room in the spread
        if self.best_bid is not None and self.best_ask is not None:
            spread = self.best_ask - self.best_bid

            # Only make markets when the spread is wide enough to matter.
            if spread >= 2:
                bid_px = min(self.best_bid + 1, fair_int - 1 - skew)
                ask_px = max(self.best_ask - 1, fair_int + 1 - skew)

                # Keep quotes sane
                if bid_px < ask_px:
                    # Quote smaller size when inventory is already large
                    base_size = 8
                    buy_size = min(base_size, self.max_buy)
                    sell_size = min(base_size, self.max_sell)

                    if self.position > 25:
                        buy_size = min(3, buy_size)
                        sell_size = min(base_size, self.max_sell)
                    elif self.position < -25:
                        buy_size = min(base_size, self.max_buy)
                        sell_size = min(3, sell_size)

                    self.buy(bid_px, buy_size)
                    self.sell(ask_px, sell_size)

        return self.orders


class Trader:
    def bid(self):
        return 15

    def run(self, state: TradingState):
        try:
            last_td = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            last_td = {}

        new_td = {}
        result = {}

        traders = {
            #EMERALDS: EmeraldsTrader,
            TOMATOES: TomatoesTrader,
        }

        for symbol, TraderClass in traders.items():
            if symbol in state.order_depths:
                try:
                    t = TraderClass(state, last_td, new_td)
                    orders = t.get_orders()
                    if orders:
                        result[symbol] = orders
                    else:
                        result[symbol] = []
                except Exception as e:
                    print(f"ERROR {symbol}: {e}")
                    result[symbol] = []

        conversions = 0
        return result, conversions, json.dumps(new_td)