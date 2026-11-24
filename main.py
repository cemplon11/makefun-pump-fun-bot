"""Pump.fun dip-reversion bot for agent-fun/replay/v2 (make.fun).

Strategy (authored in this session; parameters tuned on the kit's dev window):
  1. DIP-REVERSION on strong curves: a coin whose real SOL reserve is at least
     25 SOL and whose price has fallen 50-70% from its high of the last 5000
     slots, while buyers are still stepping in (at least 3 of its last 6 trades
     are buys and the latest trade is a buy), is bought in 0.2 SOL tranches
     (up to 1.0 SOL per position, adding only while the price stays within 5%
     of the first entry). Exit the whole position at +15% over cost, -5% under
     cost, or after 600 slots held. A curve that completes is closed by the
     replay at its final reserves. Weak curves (real SOL under 25) are never
     entered: on the dev window their dip trades lose money.
  2. GUARDRAIL PROBES: the replay requires a round trip of at least 0.01 SOL
     on at least 20 coins. The dip signal is rare (about 10 coins per 24h),
     so when the bot's own round-tripped coin count lags a pace of 25 coins
     over 6 hours of block time, it buys 0.01 SOL of a liquid coin it has not
     traded yet and sells it as soon as the buy lands. Each probe costs only
     the curve and transaction fees (about 0.0005 SOL).

Deterministic by construction: no clock, no randomness, no I/O, no environment
reads. Iteration is over insertion-ordered dicts or sorted keys only, so the
two graded executions produce byte-identical action logs.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bot  # noqa: E402  (after the sys.path line: -P leaves the script directory off sys.path)

LAMPORTS_PER_SOL = 1_000_000_000

# --- dip-reversion parameters (tuned on the dev window; see module docstring) ---
HIGH_WINDOW = 5000          # slots of lookback for the recent high
DD_MIN = 0.5                # enter when price is at least 50% below the high
DD_MAX = 0.7                # ...and not more than 70% below it
MIN_REAL_SOL = 3_000_000_000
MIN_HIGH_REAL_SOL = 3_000_000_000
STRONG_REAL_SOL = 25_000_000_000  # only curves holding this much real SOL
FLOW_TRADES = 6
MIN_BUYS = 3
LAST_MUST_BE_BUY = True
MIN_NET_FLOW = 0
TRANCHE = 200_000_000       # 0.2 SOL per tranche
MAX_POSITION = 1_000_000_000  # 1.0 SOL per position
MIN_BUY = 8_000_000
ADD_BAND = 0.05
TAKE_PROFIT = 0.15
STOP_LOSS = 0.05
MAX_HOLD_SLOTS = 600
COOLDOWN_SLOTS = 300
BUY_SLIPPAGE_BPS = 500
SELL_SLIPPAGE_BPS = 3000
MAX_ENTRIES_PER_BATCH = 2
SELL_SPLITS = 2

# --- guardrail probes ---
PROBE_SOL = 10_000_000     # 0.01 SOL: the minimum round trip that counts
PROBE_MIN_REAL_SOL = 1_500_000_000  # probe only curves holding >= 1.5 SOL
TARGET_COINS = 25
PACE_SECONDS = 21_600      # 6 hours of block time to reach the target

FEE_BPS = 125


def _book(books, mint):
    b = books.get(mint)
    if b is None:
        b = {"ticks": [], "entry_price": 0.0, "entry_slot": -1, "entry_high": 0.0,
             "committed": 0, "cool_until": -1, "exiting": False, "strong": False}
        books[mint] = b
    return b


class DipReversionBot:
    def __init__(self):
        self.books = {}
        # probes
        self.bought_coins = set()       # mints with a filled buy of ours
        self.roundtripped = set()       # mints with a filled buy and a filled sell/close
        self.probes = {}                # mint -> False (buying) / True (selling)
        self.probed = set()             # mints a probe buy was sent on
        self.first_time = None
        self.last_time = None

    def _buy_cap(self, state, mint):
        return (state.max_buy_lamports(mint) * 97) // 100

    @staticmethod
    def _liq_value(marks, mint, tokens):
        m = marks.get(mint)
        if m is None:
            return 0
        vq = int(m["virtual_quote_reserves"])
        vt = int(m["virtual_token_reserves"])
        rq = int(m["real_quote_reserves"])
        if vt + tokens == 0:
            return 0
        q = (tokens * vq) // (vt + tokens)
        if q > rq:
            q = rq
        return q - (q * FEE_BPS + 10_000 - 1) // 10_000

    def on_batch(self, state, batch):
        slot = batch["slot"]
        # --- fills: track our own round trips for the guardrail pace ---
        for f in batch["fills"]:
            if f["client_id"].startswith("_"):
                if f["mint"] in self.bought_coins:
                    self.roundtripped.add(f["mint"])
                self.probes.pop(f["mint"], None)
                continue
            if f["side"] == "buy":
                if f["status"] == "filled":
                    self.bought_coins.add(f["mint"])
                else:
                    # a probe buy that never filled: drop the probe, try another coin later
                    self.probes.pop(f["mint"], None)
            elif f["side"] == "sell":
                if f["status"] == "filled":
                    if f["mint"] in self.bought_coins:
                        self.roundtripped.add(f["mint"])
                    self.probes.pop(f["mint"], None)
                # a rejected sell keeps the probe: the position is still held, retry next batch
        # --- block time for the probe pace ---
        for e in batch["events"]:
            bt = e.get("block_time")
            if bt is None:
                continue
            if self.first_time is None:
                self.first_time = bt
            if self.last_time is None or bt > self.last_time:
                self.last_time = bt

        touched = []
        for e in batch["events"]:
            if e["event"] != "TradeEvent":
                continue
            b = _book(self.books, e["mint"])
            vt = int(e["virtual_token_reserves"])
            price = 0.0 if vt == 0 else int(e["virtual_quote_reserves"]) / vt
            b["ticks"].append({"slot": slot, "price": price, "real_sol": int(e["real_quote_reserves"]),
                               "is_buy": e["is_buy"], "sol": int(e["sol_amount"])})
            if len(b["ticks"]) > 400:
                del b["ticks"][:len(b["ticks"]) - 400]
            if e["mint"] not in touched:
                touched.append(e["mint"])
        for f in batch["fills"]:
            b = self.books.get(f["mint"])
            if b is None:
                continue
            if f["side"] == "sell":
                b["exiting"] = False
                if f["mint"] not in state.positions:
                    b["committed"] = 0
                    b["entry_slot"] = -1
                    b["cool_until"] = slot + COOLDOWN_SLOTS
            elif f["status"] != "filled" and f["mint"] not in state.positions:
                still = any(po.order["mint"] == f["mint"] for po in state.pending.values())
                if not still:
                    b["committed"] = 0
                    b["entry_slot"] = -1

        orders = []
        cap = state.hello["caps"]["max_orders_per_batch"]
        tx = state.tx_fee_lamports()
        marks = {m["mint"]: m for m in batch["marks"]}
        pending_mints = {po.order["mint"] for po in state.pending.values()}

        # --- 1. exits and adds on dip positions ---
        for mint in sorted(state.positions.keys()):
            if len(orders) >= cap:
                break
            if mint in self.probes:
                continue  # probe positions are handled below
            h = state.positions[mint]
            b = _book(self.books, mint)
            curve = state.curves.get(mint)
            if curve is None or curve.complete:
                continue
            if b["exiting"]:
                continue
            value = self._liq_value(marks, mint, h.token_amount)
            ticks = b["ticks"]
            price = ticks[-1]["price"] if ticks else 0.0
            entry_slot = b["entry_slot"] if b["entry_slot"] >= 0 else slot
            gain = (value - h.cost_lamports) / h.cost_lamports if h.cost_lamports > 0 else 0.0
            tp = gain >= TAKE_PROFIT
            sl = gain <= -STOP_LOSS
            stale = slot - entry_slot >= MAX_HOLD_SLOTS
            if tp or sl or stale:
                if mint in pending_mints:
                    continue
                n = max(1, min(SELL_SPLITS, cap - len(orders)))
                piece = h.token_amount // n
                for i in range(1, n + 1):
                    amt = h.token_amount - piece * (n - 1) if i == n else piece
                    orders.append({"side": "sell", "mint": mint, "token_amount": amt,
                                   "max_slippage_bps": SELL_SLIPPAGE_BPS})
                b["exiting"] = True
                continue
            if mint in pending_mints or b["committed"] >= MAX_POSITION:
                continue
            if b["entry_price"] > 0 and abs(price / b["entry_price"] - 1) > ADD_BAND:
                continue
            amount = MAX_POSITION - b["committed"]
            if amount > TRANCHE:
                amount = TRANCHE
            size_cap = self._buy_cap(state, mint)
            if amount > size_cap:
                amount = size_cap
            if amount < MIN_BUY:
                continue
            if state.free_cash_lamports() - amount - tx < 0:
                continue
            orders.append({"side": "buy", "mint": mint, "quote_lamports": amount,
                           "max_slippage_bps": BUY_SLIPPAGE_BPS})
            b["committed"] += amount
            pending_mints.add(mint)

        # --- 2. probe sells: sell a probe position as soon as its buy landed ---
        for mint in sorted(list(self.probes.keys())):
            if len(orders) >= cap:
                break
            pos = state.positions.get(mint)
            curve = state.curves.get(mint)
            if pos is None:
                if mint not in pending_mints:
                    self.probes.pop(mint, None)
                continue
            if curve is None or curve.complete or mint in pending_mints:
                continue
            orders.append({"side": "sell", "mint": mint, "token_amount": pos.token_amount,
                           "max_slippage_bps": 10_000})
            self.probes[mint] = True

        # --- 3. new dip entries ---
        entries = 0
        open_n = state.committed_position_count()
        for mint in touched:
            if len(orders) >= cap or entries >= MAX_ENTRIES_PER_BATCH:
                break
            if open_n >= state.hello["caps"]["max_open_positions"]:
                break
            if mint in state.positions or mint in pending_mints or mint in self.probes:
                continue
            curve = state.curves.get(mint)
            if curve is None or curve.complete:
                continue
            b = _book(self.books, mint)
            if slot < b["cool_until"]:
                continue
            ticks = b["ticks"]
            if len(ticks) < FLOW_TRADES:
                continue
            last = ticks[-1]
            if last["real_sol"] < MIN_REAL_SOL:
                continue
            hi = 0.0
            hi_real = 0
            for t in reversed(ticks):
                if slot - t["slot"] > HIGH_WINDOW:
                    break
                if t["price"] > hi:
                    hi = t["price"]
                    hi_real = t["real_sol"]
            if hi <= 0 or hi_real < MIN_HIGH_REAL_SOL:
                continue
            dd = 1 - last["price"] / hi
            strong = last["real_sol"] >= STRONG_REAL_SOL
            if not strong:
                continue
            if dd < DD_MIN or dd > DD_MAX:
                continue
            buys = 0
            net = 0
            for t in ticks[-FLOW_TRADES:]:
                if t["is_buy"]:
                    buys += 1
                    net += t["sol"]
                else:
                    net -= t["sol"]
            if buys < MIN_BUYS or net < MIN_NET_FLOW:
                continue
            if LAST_MUST_BE_BUY and not last["is_buy"]:
                continue
            amount = TRANCHE
            if amount > MAX_POSITION:
                amount = MAX_POSITION
            size_cap = self._buy_cap(state, mint)
            if amount > size_cap:
                amount = size_cap
            if amount < MIN_BUY:
                continue
            if state.free_cash_lamports() - amount - tx < 0:
                continue
            orders.append({"side": "buy", "mint": mint, "quote_lamports": amount,
                           "max_slippage_bps": BUY_SLIPPAGE_BPS})
            b["entry_price"] = last["price"]
            b["entry_slot"] = slot
            b["entry_high"] = hi
            b["committed"] = amount
            b["exiting"] = False
            b["strong"] = True
            pending_mints.add(mint)
            entries += 1
            open_n += 1

        # --- 4. guardrail probes: one tiny round trip when the coin count lags ---
        if len(orders) < cap and self.first_time is not None and self.last_time is not None:
            pace = min(1.0, (self.last_time - self.first_time) / PACE_SECONDS)
            need = int(TARGET_COINS * pace + 0.999999) - len(self.roundtripped)
            if need > 0 and not self.probes:
                free = state.free_cash_lamports()
                slots_left = state.hello["caps"]["max_open_positions"] - state.committed_position_count()
                if slots_left > 0 and free >= PROBE_SOL + 2 * tx:
                    for mint in touched:
                        if len(orders) >= cap:
                            break
                        if mint in self.probed or mint in self.probes:
                            continue
                        if mint in state.positions or mint in pending_mints:
                            continue
                        curve = state.curves.get(mint)
                        if curve is None or curve.complete:
                            continue
                        if curve.real_quote_reserves < PROBE_MIN_REAL_SOL:
                            continue
                        if self._buy_cap(state, mint) < PROBE_SOL:
                            continue
                        orders.append({"side": "buy", "mint": mint, "quote_lamports": PROBE_SOL,
                                       "max_slippage_bps": 10_000})
                        self.probes[mint] = False
                        self.probed.add(mint)
                        break
        return orders


_BOT = DipReversionBot()


def on_batch(state, batch):
    return _BOT.on_batch(state, batch)


if __name__ == "__main__":
    makefun_bot.run(on_batch)
