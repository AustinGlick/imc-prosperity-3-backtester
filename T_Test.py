import json
from typing import Any, List

try:
    # visualizer-style / official style
    from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
except ImportError:
    # backtester-style
    from prosperity3bt.datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        max_item_length = max(0, (self.max_log_length - base_length) // 3)

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        return [[listing.symbol, listing.product, listing.denomination] for listing in listings.values()]

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""

        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."

            if len(json.dumps(candidate)) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        return out


logger = Logger()

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
    def __init__(self, state, last_td, new_td):
        super().__init__(EMERALDS, state, last_td, new_td)

    def get_orders(self):
        mid = self.mid_price()
        if mid is None:
            return []

        fair = self.ema("emeralds_fair", 25, mid)
        fair_int = int(round(fair))

        for price, vol in self.asks.items():
            if price <= fair_int - 1 and self.max_buy > 0:
                self.buy(price, vol)

        for price, vol in self.bids.items():
            if price >= fair_int + 1 and self.max_sell > 0:
                self.sell(price, vol)

        if self.best_bid is not None and self.best_ask is not None:
            bid_px = min(self.best_bid + 1, fair_int)
            ask_px = max(self.best_ask - 1, fair_int)

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
    def __init__(self, state, last_td, new_td):
        super().__init__(TOMATOES, state, last_td, new_td)

    def get_orders(self):
        mid = self.mid_price()
        if mid is None:
            return []

        ema_mid = self.ema("tomatoes_ema_mid", 60, mid)
        imb = self.imbalance_l1()
        fair = ema_mid + 12.0 * imb
        fair_int = int(round(fair))

        edge = 2

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

        inv_ratio = self.position / self.pos_limit if self.pos_limit else 0.0
        skew = int(round(inv_ratio * 2))

        if self.best_bid is not None and self.best_ask is not None:
            spread = self.best_ask - self.best_bid

            if spread >= 2:
                bid_px = min(self.best_bid + 1, fair_int - 1 - skew)
                ask_px = max(self.best_ask - 1, fair_int + 1 - skew)

                if bid_px < ask_px:
                    base_size = 8
                    buy_size = min(base_size, self.max_buy)
                    sell_size = min(base_size, self.max_sell)

                    if self.position > 25:
                        buy_size = min(3, buy_size)
                    elif self.position < -25:
                        sell_size = min(3, sell_size)

                    self.buy(bid_px, buy_size)
                    self.sell(ask_px, sell_size)

        return self.orders


class Trader:
    def run(self, state: TradingState):
        try:
            last_td = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            last_td = {}

        new_td = {}
        result = {}

        traders = {
            EMERALDS: EmeraldsTrader,
            TOMATOES: TomatoesTrader,
        }

        for symbol, TraderClass in traders.items():
            if symbol in state.order_depths:
                try:
                    t = TraderClass(state, last_td, new_td)
                    orders = t.get_orders()
                    result[symbol] = orders if orders else []
                except Exception as e:
                    logger.print(f"ERROR {symbol}: {e}")
                    result[symbol] = []

        conversions = 0
        trader_data = json.dumps(new_td)

        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data