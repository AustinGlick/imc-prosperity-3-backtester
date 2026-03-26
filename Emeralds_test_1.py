from prosperity3bt.datamodel import OrderDepth, TradingState, Order, ProsperityEncoder
import json
from typing import Any

# ── constants ──────────────────────────────────────────────────────────────
EMERALDS = "EMERALDS"
TOMATOES = "TOMATOES"

POS_LIMITS = {EMERALDS: 80, TOMATOES: 80}


# ── logger ────────────────────────────────────────────────────────────────
import json
from typing import Any

try:
    # Works in the visualizer-style environment
    from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
except ImportError:
    # Works in the prosperity3bt backtester
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

# ── base class ─────────────────────────────────────────────────────────────
class ProductTrader:
    """Handles all the repetitive setup so your strategy class stays clean."""

    def __init__(self, symbol, state, last_td, new_td):
        self.symbol = symbol
        self.state = state
        self.last_td = last_td
        self.new_td = new_td
        self.orders = []

        # position
        self.pos_limit = POS_LIMITS.get(symbol, 0)
        self.position = state.position.get(symbol, 0)
        self.max_buy = self.pos_limit - self.position
        self.max_sell = self.pos_limit + self.position

        # order book
        od = state.order_depths.get(symbol, OrderDepth())
        self.bids = {p: abs(v) for p, v in sorted(od.buy_orders.items(), reverse=True)}
        self.asks = {p: abs(v) for p, v in sorted(od.sell_orders.items())}

        # price levels
        self.best_bid = max(self.bids) if self.bids else None
        self.best_ask = min(self.asks) if self.asks else None
        self.bid_wall = min(self.bids) if self.bids else None
        self.ask_wall = max(self.asks) if self.asks else None
        self.wall_mid = (
            (self.bid_wall + self.ask_wall) / 2
            if self.bid_wall is not None and self.ask_wall is not None
            else None
        )

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
        return self.orders


# ── strategy: Emeralds ─────────────────────────────────────────────────────
class EmeraldsTrader(ProductTrader):
    def __init__(self, state, last_td, new_td):
        super().__init__(EMERALDS, state, last_td, new_td)

    def get_orders(self):
        if self.wall_mid is None:
            return self.orders

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

        self.buy(bid_price, self.max_buy)
        self.sell(ask_price, self.max_sell)

        return self.orders


# ── strategy: Tomatoes ─────────────────────────────────────────────────────
class TomatoesTrader(ProductTrader):
    def __init__(self, state, last_td, new_td):
        super().__init__(TOMATOES, state, last_td, new_td)

    def get_orders(self):
        if self.wall_mid is None:
            return self.orders

        for price, vol in self.asks.items():
            if price < self.wall_mid:
                self.buy(price, vol)

        for price, vol in self.bids.items():
            if price > self.wall_mid:
                self.sell(price, vol)

        self.buy(self.bid_wall + 1, self.max_buy)
        self.sell(self.ask_wall - 1, self.max_sell)

        return self.orders


# ── entry point ────────────────────────────────────────────────────────────
class Trader:
    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        result = {}
        conversions = 0
        trader_data = ""

        try:
            last_td = json.loads(state.traderData) if state.traderData else {}
        except Exception as e:
            logger.print("Failed to parse traderData:", e)
            last_td = {}

        new_td = {}

        traders = {
            EMERALDS: EmeraldsTrader,
            # TOMATOES: TomatoesTrader,
        }

        for symbol, TraderClass in traders.items():
            if symbol in state.order_depths:
                try:
                    t = TraderClass(state, last_td, new_td)
                    result[symbol] = t.get_orders()
                except Exception as e:
                    logger.print(f"ERROR {symbol}: {e}")

        trader_data = json.dumps(new_td)
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data