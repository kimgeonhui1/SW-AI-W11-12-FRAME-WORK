"""Server-authoritative, two-player Texas Hold'em rules for Poker Lab."""
from collections import Counter
from itertools import combinations
import random


PLAYERS = ("human", "bot")
RANKS = "23456789TJQKA"
SUITS = ("♠", "♥", "♦", "♣")
HAND_NAMES = (
    "하이 카드", "원 페어", "투 페어", "트리플", "스트레이트",
    "플러시", "풀 하우스", "포 카드", "스트레이트 플러시",
)


class RuleError(ValueError):
    """An action is invalid for the current hand state."""


def new_deck(rng=None):
    deck = [rank + suit for rank in RANKS for suit in SUITS]
    (rng or random.SystemRandom()).shuffle(deck)
    return deck


def evaluate_five(cards):
    """Return a comparable (category, kickers...) tuple for exactly five cards."""
    if len(cards) != 5 or len(set(cards)) != 5:
        raise ValueError("exactly five unique cards are required")
    try:
        ranks = sorted((RANKS.index(card[0]) + 2 for card in cards), reverse=True)
        suits = [card[1:] for card in cards]
    except (IndexError, ValueError) as exc:
        raise ValueError("invalid card") from exc
    if any(suit not in SUITS for suit in suits):
        raise ValueError("invalid card suit")

    counts = Counter(ranks)
    groups = sorted(((count, rank) for rank, count in counts.items()), reverse=True)
    unique = set(ranks)
    if 14 in unique:
        unique.add(1)  # A-2-3-4-5 wheel
    straight_high = next((high for high in range(14, 4, -1) if all(rank in unique for rank in range(high - 4, high + 1))), 0)
    flush = len(set(suits)) == 1

    if flush and straight_high:
        return (8, straight_high)
    if groups[0][0] == 4:
        quad = groups[0][1]
        kicker = max(rank for rank in ranks if rank != quad)
        return (7, quad, kicker)
    if groups[0][0] == 3 and groups[1][0] == 2:
        return (6, groups[0][1], groups[1][1])
    if flush:
        return (5, *ranks)
    if straight_high:
        return (4, straight_high)
    if groups[0][0] == 3:
        trip = groups[0][1]
        return (3, trip, *sorted((rank for rank in ranks if rank != trip), reverse=True))
    pairs = sorted((rank for rank, count in counts.items() if count == 2), reverse=True)
    if len(pairs) == 2:
        kicker = next(rank for rank in ranks if rank not in pairs)
        return (2, pairs[0], pairs[1], kicker)
    if len(pairs) == 1:
        pair = pairs[0]
        return (1, pair, *sorted((rank for rank in ranks if rank != pair), reverse=True))
    return (0, *ranks)


def best_hand(cards):
    """Return (rank tuple, selected five cards) from five to seven cards."""
    if not 5 <= len(cards) <= 7 or len(set(cards)) != len(cards):
        raise ValueError("five to seven unique cards are required")
    ranked = ((evaluate_five(hand), hand) for hand in combinations(cards, 5))
    return max(ranked, key=lambda item: item[0])


class PokerEngine:
    """Two-seat no-limit Hold'em engine; the human is the first button."""

    def __init__(self, starting_stacks=None, small_blind=10, big_blind=20, deck_factory=new_deck):
        self.small_blind = self._positive_chip_amount(small_blind, "small blind")
        self.big_blind = self._positive_chip_amount(big_blind, "big blind")
        if self.big_blind <= self.small_blind:
            raise ValueError("big blind must exceed small blind")
        self.starting_stacks = dict(starting_stacks or {"human": 1000, "bot": 1000})
        if set(self.starting_stacks) != set(PLAYERS):
            raise ValueError("starting_stacks must define human and bot")
        for player, amount in self.starting_stacks.items():
            if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                raise ValueError(f"{player} stack must be a non-negative integer")
        if sum(self.starting_stacks.values()) <= 0:
            raise ValueError("at least one player must have chips")
        self.initial_chips = sum(self.starting_stacks.values())
        self.deck_factory = deck_factory
        self.stacks = dict(self.starting_stacks)
        self.hand_no = 0
        self.button = "bot"  # start_hand toggles this, so human has the first button
        self.hand = None

    @staticmethod
    def _positive_chip_amount(value, label):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{label} must be a positive integer")
        return value

    @property
    def phase(self):
        return self.hand["phase"] if self.hand else "idle"

    @property
    def turn(self):
        return self.hand["pending"][0] if self.hand and self.hand["pending"] else None

    @property
    def hand_over(self):
        return bool(self.hand and self.hand["hand_over"])

    def restore_for_next_hand(self, stacks, completed_hand_no):
        """Restore only the durable match ledger; an unfinished hand is never restored."""
        if self.hand is not None or not isinstance(completed_hand_no, int) or completed_hand_no < 0:
            raise ValueError("engine must be idle and completed_hand_no non-negative")
        if set(stacks) != set(PLAYERS) or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in stacks.values()):
            raise ValueError("restored stacks must be non-negative integer amounts")
        if sum(stacks.values()) <= 0:
            raise ValueError("restored match has no chips")
        self.stacks = dict(stacks)
        self.initial_chips = sum(stacks.values())
        self.starting_stacks = dict(stacks)
        self.hand_no = completed_hand_no

    def start_hand(self, deck=None):
        if self.hand and not self.hand_over:
            raise RuleError("the current hand is still active")
        if any(self.stacks[player] <= 0 for player in PLAYERS):
            raise RuleError("the match is over because a player has no chips")
        self.button = "human" if self.hand_no % 2 == 0 else "bot"
        self.hand_no += 1
        cards = list(deck if deck is not None else self.deck_factory())
        if len(cards) != 52 or len(set(cards)) != 52 or set(cards) != {rank + suit for rank in RANKS for suit in SUITS}:
            raise ValueError("deck must contain every standard card exactly once")

        other = self._other(self.button)
        holes = {"human": [], "bot": []}
        # Deal one card clockwise at a time, beginning with the button.
        for _ in range(2):
            holes[self.button].append(cards[len(holes["human"]) + len(holes["bot"])])
            index = len(holes["human"]) + len(holes["bot"])
            holes[other].append(cards[index])

        self.hand = {
            "phase": "preflop", "board": [], "holes": holes, "deck": cards,
            "start_stacks": dict(self.stacks),
            "deck_index": 4, "button": self.button, "street_bets": {p: 0 for p in PLAYERS},
            "total_bets": {p: 0 for p in PLAYERS}, "current_bet": 0,
            "min_raise": self.big_blind, "can_raise": {p: True for p in PLAYERS},
            "pending": [], "actions": [], "hand_over": False, "result": None,
            "message": "",
        }
        self._post_blind(self.button, self.small_blind)
        self._post_blind(other, self.big_blind)
        self.hand["current_bet"] = max(self.hand["street_bets"].values())
        order = (self.button, other)
        if any(self.stacks[player] == 0 for player in PLAYERS):
            # An all-in blind cannot offer a free option to bet; the covering
            # player only acts if they still owe chips against that all-in.
            self.hand["pending"] = [p for p in order if self.stacks[p] > 0 and self._to_call(p) > 0]
        else:
            # The big blind retains its option to check after a button call.
            self.hand["pending"] = self._ordered_players(order)
        self.hand["message"] = f"블라인드 {self.small_blind}/{self.big_blind} · {self._label(self.button)}가 먼저 행동합니다."
        self._continue_if_ready()
        self._assert_chip_conservation()
        return self.snapshot()

    @staticmethod
    def _other(player):
        return "bot" if player == "human" else "human"

    @staticmethod
    def _label(player):
        return "사람" if player == "human" else "봇"

    def _ordered_players(self, order, owe_only=False):
        if not owe_only:
            return [player for player in order if self.stacks[player] > 0]
        return [player for player in order if self.stacks[player] > 0 and self._to_call(player) > 0]

    def _post_blind(self, player, amount):
        paid = min(amount, self.stacks[player])
        self.stacks[player] -= paid
        self.hand["street_bets"][player] += paid
        self.hand["total_bets"][player] += paid

    def _to_call(self, player):
        hand = self.hand
        opponent = self._other(player)
        target = hand["current_bet"]
        # An all-in opponent cannot be made to contest chips beyond their total contribution.
        if self.stacks[opponent] == 0:
            target = min(target, hand["street_bets"][opponent])
        return max(0, min(target - hand["street_bets"][player], self.stacks[player]))

    def _raise_bounds(self, player):
        hand = self.hand
        own_max = hand["street_bets"][player] + self.stacks[player]
        # No-limit raises may exceed the opponent's effective stack. Any
        # unmatched excess is returned when the hand closes.
        return hand["current_bet"] + hand["min_raise"], own_max

    def legal_actions(self, player="human"):
        if not self.hand or self.hand_over or self.turn != player:
            return []
        hand = self.hand
        call = self._to_call(player)
        actions = ["fold"]
        actions.append("call" if call else "check")
        opponent = self._other(player)
        min_to, max_to = self._raise_bounds(player)
        if hand["can_raise"][player] and self.stacks[opponent] > 0 and max_to >= min_to:
            actions.append("bet" if hand["current_bet"] == 0 else "raise")
        if self.stacks[player] > 0 and (call > 0 or self.stacks[opponent] > 0):
            actions.append("all_in")
        return actions

    def act(self, player, action, to=None):
        if not self.hand or self.hand_over:
            raise RuleError("there is no active hand")
        if player != self.turn:
            raise RuleError("it is not this player's turn")
        if action not in self.legal_actions(player):
            raise RuleError("action is not legal in the current state")
        hand = self.hand
        street = hand["phase"]
        opponent = self._other(player)
        paid = 0
        all_in = False

        if action == "fold":
            hand["actions"].append({"player": player, "action": action, "street": street, "paid": 0})
            self._settle_fold(opponent)
            self._assert_chip_conservation()
            return self.snapshot()

        if action in ("check", "call"):
            due = self._to_call(player)
            if action == "check" and due:
                raise RuleError("cannot check while facing a wager")
            if action == "call" and not due:
                raise RuleError("nothing to call; check instead")
            paid = min(due, self.stacks[player])
            self._pay(player, paid)
            all_in = self.stacks[player] == 0
            hand["can_raise"][player] = False
            hand["pending"] = [p for p in hand["pending"] if p != player]
            if any(self.stacks[p] == 0 for p in PLAYERS):
                hand["pending"] = [p for p in hand["pending"] if self._to_call(p) > 0]
            hand["actions"].append({"player": player, "action": action, "street": street, "paid": paid, "allIn": all_in})
            hand["message"] = f"{self._label(player)}가 {'체크' if action == 'check' else f'{paid}칩 콜'}했습니다."
        elif action in ("bet", "raise", "all_in"):
            current = hand["current_bet"]
            contribution = hand["street_bets"][player]
            target = contribution + self.stacks[player] if action == "all_in" else to
            if not isinstance(target, int) or isinstance(target, bool):
                raise RuleError("bet target must be an integer chip amount")
            if action == "all_in" and target <= current:
                # A short stack can shove less than the wager to call. This is
                # an all-in call, not a raise, and does not change current_bet.
                paid = self.stacks[player]
                self._pay(player, paid)
                hand["can_raise"][player] = False
                hand["pending"] = [p for p in hand["pending"] if p != player]
                hand["pending"] = [p for p in hand["pending"] if self._to_call(p) > 0]
                hand["actions"].append({"player": player, "action": "all_in", "street": street, "paid": paid, "allIn": True})
                hand["message"] = f"{self._label(player)}가 {paid}칩으로 올인 콜했습니다."
                self._continue_if_ready()
                self._assert_chip_conservation()
                return self.snapshot()
            if target <= current or target <= contribution:
                raise RuleError("a bet or raise must exceed the current wager")
            if action == "bet" and current != 0:
                raise RuleError("use raise while facing a wager")
            if action == "raise" and current == 0:
                raise RuleError("use bet when no wager exists")
            if not hand["can_raise"][player]:
                raise RuleError("action was not reopened for a raise")
            pay = target - contribution
            if pay > self.stacks[player]:
                raise RuleError("bet exceeds the player's stack")
            min_to = current + hand["min_raise"]
            is_all_in = pay == self.stacks[player]
            if target < min_to and not is_all_in:
                raise RuleError(f"minimum raise is to {min_to}")
            _, max_to = self._raise_bounds(player)
            if target > max_to and not is_all_in:
                raise RuleError(f"bet exceeds the player's stack")

            raise_size = target - current
            full_raise = raise_size >= hand["min_raise"]
            self._pay(player, pay)
            hand["current_bet"] = target
            hand["can_raise"][player] = False
            if full_raise:
                hand["min_raise"] = raise_size
                hand["can_raise"][opponent] = True
            # A short all-in requires a response but does not reopen raising for an
            # opponent who already acted since the last full raise.
            hand["pending"] = [opponent] if self.stacks[opponent] > 0 and self._to_call(opponent) > 0 else []
            paid = pay
            all_in = self.stacks[player] == 0
            hand["actions"].append({"player": player, "action": action, "street": street, "to": target, "paid": paid, "allIn": all_in, "fullRaise": full_raise})
            hand["message"] = f"{self._label(player)}가 {target}칩으로 {'올인' if all_in else '베팅'}했습니다."

        self._continue_if_ready()
        self._assert_chip_conservation()
        return self.snapshot()

    def _pay(self, player, amount):
        if amount < 0 or amount > self.stacks[player]:
            raise RuleError("bet exceeds the player's stack")
        self.stacks[player] -= amount
        self.hand["street_bets"][player] += amount
        self.hand["total_bets"][player] += amount

    def _continue_if_ready(self):
        hand = self.hand
        if hand["hand_over"] or hand["pending"]:
            return
        # Guard against a missed response in the state machine.
        owing = [p for p in PLAYERS if self.stacks[p] > 0 and self._to_call(p) > 0]
        if owing:
            hand["pending"] = self._ordered_players(owing)
            return
        if any(self.stacks[p] == 0 for p in PLAYERS):
            self._return_uncalled()
            self._runout_and_showdown()
            return
        if hand["phase"] == "river":
            self._settle_showdown()
            return
        self._deal_next_street()

    def _deal_next_street(self):
        hand = self.hand
        index = hand["deck_index"]
        if hand["phase"] == "preflop":
            hand["board"].extend(hand["deck"][index + 1:index + 4])
            hand["deck_index"] = index + 4
            hand["phase"] = "flop"
        elif hand["phase"] == "flop":
            hand["board"].append(hand["deck"][index + 1])
            hand["deck_index"] = index + 2
            hand["phase"] = "turn"
        elif hand["phase"] == "turn":
            hand["board"].append(hand["deck"][index + 1])
            hand["deck_index"] = index + 2
            hand["phase"] = "river"
        else:
            self._settle_showdown()
            return
        hand["street_bets"] = {p: 0 for p in PLAYERS}
        hand["current_bet"] = 0
        hand["min_raise"] = self.big_blind
        hand["can_raise"] = {p: True for p in PLAYERS}
        first = self._other(hand["button"])
        hand["pending"] = self._ordered_players((first, hand["button"]))
        hand["message"] = f"{self._street_label(hand['phase'])} 카드가 공개됐습니다."

    def _runout_and_showdown(self):
        while self.hand["phase"] != "river":
            self._deal_next_street()
            if self.hand["hand_over"]:
                return
        self._settle_showdown()

    def _return_uncalled(self):
        hand = self.hand
        human, bot = (hand["total_bets"][p] for p in PLAYERS)
        if human == bot:
            return
        leader = "human" if human > bot else "bot"
        other = self._other(leader)
        refund = hand["total_bets"][leader] - hand["total_bets"][other]
        if refund > hand["street_bets"][leader]:
            raise RuleError("uncalled chips span a completed betting street")
        self.stacks[leader] += refund
        hand["total_bets"][leader] -= refund
        hand["street_bets"][leader] -= refund
        hand["message"] += f" 미응수 {refund}칩은 반환됐습니다."

    def _settle_fold(self, winner):
        self._return_uncalled()
        pot = sum(self.hand["total_bets"].values())
        self.stacks[winner] += pot
        self.hand["total_bets"] = {p: 0 for p in PLAYERS}
        self.hand["street_bets"] = {p: 0 for p in PLAYERS}
        self.hand["current_bet"] = 0
        self.hand["pending"] = []
        self.hand["hand_over"] = True
        self.hand["phase"] = "complete"
        self.hand["result"] = {"winner": winner, "reason": "fold", "pot": pot, "payouts": {winner: pot, self._other(winner): 0}}
        self.hand["message"] = f"{self._label(self._other(winner))}가 폴드했습니다. {self._label(winner)} 승리 · {pot}칩 정산."

    def _settle_showdown(self):
        if self.hand["hand_over"]:
            return
        self._return_uncalled()
        ranks = {player: best_hand(self.hand["holes"][player] + self.hand["board"])[0] for player in PLAYERS}
        pot = sum(self.hand["total_bets"].values())
        if ranks["human"] == ranks["bot"]:
            split, odd = divmod(pot, 2)
            payouts = {"human": split, "bot": split}
            if odd:
                payouts[self._other(self.hand["button"])] += odd
            winner = "tie"
        else:
            winner = "human" if ranks["human"] > ranks["bot"] else "bot"
            payouts = {player: pot if player == winner else 0 for player in PLAYERS}
        for player in PLAYERS:
            self.stacks[player] += payouts[player]
        labels = {player: HAND_NAMES[ranks[player][0]] for player in PLAYERS}
        self.hand["total_bets"] = {p: 0 for p in PLAYERS}
        self.hand["street_bets"] = {p: 0 for p in PLAYERS}
        self.hand["current_bet"] = 0
        self.hand["pending"] = []
        self.hand["hand_over"] = True
        self.hand["phase"] = "showdown"
        self.hand["result"] = {"winner": winner, "reason": "showdown", "pot": pot, "payouts": payouts, "hands": labels, "rankValues": ranks}
        self.hand["message"] = "무승부 · 팟을 나눴습니다." if winner == "tie" else f"쇼다운 · {self._label(winner)} 승리 ({labels[winner]}) · {pot}칩 정산."

    def snapshot(self):
        if not self.hand:
            return None
        hand = self.hand
        human_to_act = self.turn == "human"
        return {
            "handNo": self.hand_no,
            "phase": hand["phase"],
            "turn": self.turn,
            "button": hand["button"],
            "humanStack": self.stacks["human"],
            "botStack": self.stacks["bot"],
            "startingHumanStack": hand["start_stacks"]["human"],
            "startingBotStack": hand["start_stacks"]["bot"],
            "pot": sum(hand["total_bets"].values()),
            "toCall": self._to_call("human") if human_to_act else 0,
            "minRaiseTo": self._raise_bounds("human")[0] if human_to_act else None,
            "maxRaiseTo": self._raise_bounds("human")[1] if human_to_act else None,
            "legalActions": self.legal_actions("human"),
            "humanCards": list(hand["holes"]["human"]),
            "botCards": list(hand["holes"]["bot"]) if hand["phase"] == "showdown" else [],
            "botCardsRevealed": hand["phase"] == "showdown",
            "board": list(hand["board"]),
            "humanCommitted": hand["total_bets"]["human"],
            "botCommitted": hand["total_bets"]["bot"],
            "actions": [dict(action) for action in hand["actions"]],
            "result": dict(hand["result"]) if hand["result"] else None,
            "handOver": hand["hand_over"],
            "matchOver": hand["hand_over"] and any(self.stacks[p] == 0 for p in PLAYERS),
            "message": hand["message"],
        }

    def _assert_chip_conservation(self):
        if not self.hand:
            return
        hand = self.hand
        if any(value < 0 for value in self.stacks.values()):
            raise AssertionError("negative player stack")
        if hand["hand_over"]:
            total = sum(self.stacks.values())
        else:
            total = sum(self.stacks.values()) + sum(hand["total_bets"].values())
        if total != self.initial_chips:
            raise AssertionError(f"chip conservation failed: expected {self.initial_chips}, got {total}")

    @staticmethod
    def _street_label(street):
        return {"flop": "플롭", "turn": "턴", "river": "리버"}.get(street, street)
