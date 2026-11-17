"""Server-authoritative no-limit Hold'em for 2-4 seats, used by multiplayer rooms.

The practice mode (person vs bot) keeps using engine.PokerEngine unchanged; this module
generalises the same rules to 2-4 participants and adds side pots.

Rules applied (see projects/poker_demo/MULTIPLAYER.md, "Table rules"):
- Seats are numbered clockwise. A hand is played by a fixed list of participant seats.
- Heads-up: the button posts the small blind, acts first pre-flop and last afterwards (TDA).
  3-4 players: small blind left of the button, big blind next, pre-flop action starts left of
  the big blind; after the flop the first active seat left of the button acts first.
- Cards are dealt one at a time starting left of the button (heads-up: the big blind first).
- A blind larger than the stack is posted all-in.
- Minimum bet is the big blind; a raise must be at least the last full bet/raise of the round.
  An all-in short of a full raise does not reopen raising to players who already acted unless
  the total increase they face since their last action is at least a full raise (TDA).
- Unmatched chips (the part of the largest contribution nobody else matched) are returned at
  the end of each betting round.
- Pots are built from every contribution, folded players included; only players still in the
  hand are eligible. Each pot is awarded separately; an odd chip goes to the eligible winner
  closest to the left of the button (TDA).
"""
from collections import Counter
from itertools import combinations
import random

from engine import HAND_NAMES, RANKS, SUITS, RuleError, best_hand, new_deck

STREETS = ("preflop", "flop", "turn", "river")
MIN_SEATS, MAX_SEATS = 2, 4


class TableHand:
    """One hand. Seat numbers are 0..max_seats-1; only `seats` take part."""

    def __init__(self, stacks, button, small_blind=10, big_blind=20, deck=None, max_seats=MAX_SEATS):
        """stacks: {seat: chips} of the participants (each > 0). button: the button seat (a participant)."""
        if not MIN_SEATS <= len(stacks) <= MAX_SEATS:
            raise ValueError("a hand needs 2 to 4 participants")
        for seat, chips in stacks.items():
            if not isinstance(seat, int) or not 0 <= seat < max_seats:
                raise ValueError("invalid seat")
            if not isinstance(chips, int) or isinstance(chips, bool) or chips <= 0:
                raise ValueError("each participant needs a positive integer stack")
        if button not in stacks:
            raise ValueError("the button must be a participant")
        if not (isinstance(small_blind, int) and isinstance(big_blind, int) and 0 < small_blind < big_blind):
            raise ValueError("invalid blinds")
        self.max_seats = max_seats
        self.small_blind, self.big_blind = small_blind, big_blind
        self.seats = sorted(stacks)  # clockwise order
        self.start_stacks = dict(stacks)
        self.stacks = dict(stacks)
        self.initial_chips = sum(stacks.values())
        self.button = button
        cards = list(deck if deck is not None else new_deck())
        if len(cards) != 52 or set(cards) != {r + s for r in RANKS for s in SUITS}:
            raise ValueError("deck must contain every standard card exactly once")
        self.deck = cards
        heads_up = len(self.seats) == 2
        self.sb = button if heads_up else self.next_seat(button)
        self.bb = self.next_seat(self.sb)
        # deal one card at a time, starting left of the button
        order = self.order_from(self.next_seat(button))
        self.holes = {seat: [] for seat in self.seats}
        index = 0
        for _ in range(2):
            for seat in order:
                self.holes[seat].append(cards[index])
                index += 1
        self.deck_index = index  # next card is the first burn card
        self.board = []
        self.street = "preflop"
        self.street_bets = {seat: 0 for seat in self.seats}
        self.total_bets = {seat: 0 for seat in self.seats}
        self.folded = set()
        self.acted_at = {seat: None for seat in self.seats}  # table bet when the seat last acted this round
        self.current_bet = 0
        self.min_raise = big_blind
        self.actions = []
        self.returns = []  # unmatched chips returned: {"seat", "amount", "street"}
        self.hand_over = False
        self.result = None
        self.turn = None
        self._post(self.sb, small_blind)
        self._post(self.bb, big_blind)
        self.blinds_posted = {self.sb: self.total_bets[self.sb], self.bb: self.total_bets[self.bb]}
        # House rule: the amount to call is the full big blind even when the big blind posted
        # less all-in; anything above what the short blind can match is returned at round end.
        self.current_bet = big_blind
        # pre-flop: heads-up the button (SB) acts first; otherwise left of the big blind
        first = self.sb if heads_up else self.next_seat(self.bb)
        self._advance(first, include_start=True)
        self._check_conservation()

    # ── seat order helpers ─────────────────────────────────────────────────

    def next_seat(self, seat, among=None):
        group = sorted(among if among is not None else self.seats)
        later = [s for s in group if s > seat]
        return later[0] if later else group[0]

    def order_from(self, seat):
        """Participants clockwise starting at `seat` (which must be a participant)."""
        i = self.seats.index(seat)
        return self.seats[i:] + self.seats[:i]

    def live(self):
        return [s for s in self.seats if s not in self.folded]

    def can_act(self, seat):
        return seat not in self.folded and self.stacks[seat] > 0

    # ── actions ───────────────────────────────────────────────────────────

    def to_call(self, seat):
        return max(0, min(self.current_bet - self.street_bets[seat], self.stacks[seat]))

    def raise_bounds(self, seat):
        return self.current_bet + self.min_raise, self.street_bets[seat] + self.stacks[seat]

    def may_raise(self, seat):
        """Raising needs another live player with chips, and an open action for this seat."""
        others = [s for s in self.live() if s != seat and self.stacks[s] > 0]
        if not others or self.stacks[seat] <= self.to_call(seat):
            return False
        last = self.acted_at[seat]
        return last is None or self.current_bet - last >= self.min_raise

    def legal_actions(self, seat):
        if self.hand_over or seat != self.turn:
            return []
        call = self.to_call(seat)
        actions = ["fold", "call" if call else "check"]
        raise_ok = self.may_raise(seat)
        min_to, max_to = self.raise_bounds(seat)
        if raise_ok and max_to >= min_to:
            actions.append("bet" if self.current_bet == 0 else "raise")
        # all-in is a call when it does not exceed the call amount, otherwise a (possibly short) raise
        if self.stacks[seat] > 0 and (self.stacks[seat] <= call or raise_ok):
            actions.append("all_in")
        return actions

    def act(self, seat, action, to=None):
        if self.hand_over:
            raise RuleError("there is no active hand")
        if seat != self.turn:
            raise RuleError("it is not this player's turn")
        if action not in self.legal_actions(seat):
            raise RuleError("action is not legal in the current state")
        street = self.street
        record = {"seat": seat, "action": action, "street": street, "paid": 0, "allIn": False}
        if action == "fold":
            self.folded.add(seat)
            self.actions.append(record)
            if len(self.live()) == 1:
                self._finish_round()
                self._settle()
            else:
                self._advance(self.next_seat(seat))
            self._check_conservation()
            return
        call = self.to_call(seat)
        if action in ("check", "call"):
            if action == "check" and call:
                raise RuleError("cannot check while facing a wager")
            if action == "call" and not call:
                raise RuleError("nothing to call; check instead")
            self._pay(seat, call)
            record["paid"] = call
        else:
            contribution = self.street_bets[seat]
            target = contribution + self.stacks[seat] if action == "all_in" else to
            if not isinstance(target, int) or isinstance(target, bool):
                raise RuleError("bet target must be an integer chip amount")
            if action == "all_in" and target <= self.current_bet:
                pay = self.stacks[seat]  # all-in call for the same or less than the call amount
                self._pay(seat, pay)
                record["paid"] = pay
            else:
                if action == "bet" and self.current_bet != 0:
                    raise RuleError("use raise while facing a wager")
                if action == "raise" and self.current_bet == 0:
                    raise RuleError("use bet when no wager exists")
                if not self.may_raise(seat):
                    raise RuleError("raising was not reopened for this player")
                min_to, max_to = self.raise_bounds(seat)
                if target > max_to:
                    raise RuleError("bet exceeds the player's stack")
                if target < min_to and target != max_to:
                    raise RuleError(f"minimum raise is to {min_to}")
                if target <= self.current_bet:
                    raise RuleError("a bet or raise must exceed the current wager")
                increase = target - self.current_bet
                full = increase >= self.min_raise
                if full:
                    self.min_raise = increase  # a full raise sets the next minimum
                self.current_bet = target
                pay = target - contribution
                self._pay(seat, pay)
                record["paid"] = pay
                record["to"] = target
                record["fullRaise"] = full
        record["allIn"] = self.stacks[seat] == 0
        self.acted_at[seat] = self.current_bet
        self.actions.append(record)
        self._advance(self.next_seat(seat))
        self._check_conservation()

    def _post(self, seat, amount):
        self._pay(seat, min(amount, self.stacks[seat]))

    def _pay(self, seat, amount):
        if amount < 0 or amount > self.stacks[seat]:
            raise RuleError("bet exceeds the player's stack")
        self.stacks[seat] -= amount
        self.street_bets[seat] += amount
        self.total_bets[seat] += amount

    # ── round flow ─────────────────────────────────────────────────────────

    def needs_action(self, seat):
        if not self.can_act(seat):
            return False
        others_with_chips = [s for s in self.live() if s != seat and self.stacks[s] > 0]
        if self.street_bets[seat] < self.current_bet:
            return True
        if not others_with_chips:
            return False  # nobody left to bet against; a free option would be meaningless
        return self.acted_at[seat] is None or self.acted_at[seat] < self.current_bet

    def _advance(self, start, include_start=True):
        """Give the turn to the first seat from `start` clockwise that still has to act, or close the round."""
        for seat in self.order_from(start):
            if self.needs_action(seat):
                self.turn = seat
                return
        self.turn = None
        self._finish_round()
        if self.hand_over:
            return
        live_with_chips = [s for s in self.live() if self.stacks[s] > 0]
        if self.street == "river" or len(live_with_chips) <= 1:
            while self.street != "river":
                self._deal_next_street()
            self._settle()
            return
        self._deal_next_street()
        first = self.next_seat(self.button)
        self._advance(first)

    def _finish_round(self):
        """Return unmatched chips: the top contribution beyond the second highest goes back."""
        ordered = sorted(self.seats, key=lambda s: self.total_bets[s], reverse=True)
        top, second = ordered[0], ordered[1]
        excess = self.total_bets[top] - self.total_bets[second]
        if excess > 0:
            self.total_bets[top] -= excess
            self.street_bets[top] -= excess
            self.stacks[top] += excess
            self.returns.append({"seat": top, "amount": excess, "street": self.street})
        if not self.hand_over:
            for seat in self.seats:
                self.street_bets[seat] = 0
            self.current_bet = 0
            self.min_raise = self.big_blind
            self.acted_at = {seat: None for seat in self.seats}

    def _deal_next_street(self):
        i = self.deck_index
        if self.street == "preflop":
            self.board += self.deck[i + 1:i + 4]
            self.deck_index = i + 4
            self.street = "flop"
        elif self.street == "flop":
            self.board.append(self.deck[i + 1])
            self.deck_index = i + 2
            self.street = "turn"
        elif self.street == "turn":
            self.board.append(self.deck[i + 1])
            self.deck_index = i + 2
            self.street = "river"

    # ── pots and settlement ───────────────────────────────────────────────

    def pots(self):
        """Pots from the current contributions: [{"amount", "eligible"}]; main pot first."""
        return build_pots(self.total_bets, self.live())

    def live_pots(self):
        """Pots as shown while betting continues: only all-in players split off side pots."""
        return build_pots(self.total_bets, self.live(), {s for s in self.live() if self.stacks[s] == 0})

    def odd_chip_order(self, seats):
        """Seats ordered clockwise starting left of the button (who gets odd chips first)."""
        return [s for s in self.order_from(self.next_seat(self.button)) if s in seats]

    def _settle(self):
        live = self.live()
        payouts = {seat: 0 for seat in self.seats}
        pots = []
        ranks = {}
        if len(live) == 1:
            winner = live[0]
            for pot in self.pots():
                payouts[winner] += pot["amount"]
                pots.append({**pot, "winners": [winner], "shares": {winner: pot["amount"]}})
            reason = "fold"
        else:
            ranks = {s: best_hand(self.holes[s] + self.board)[0] for s in live}
            for pot in self.pots():
                best = max(ranks[s] for s in pot["eligible"])
                winners = [s for s in pot["eligible"] if ranks[s] == best]
                share, odd = divmod(pot["amount"], len(winners))
                shares = {s: share for s in winners}
                for s in self.odd_chip_order(winners)[:odd]:
                    shares[s] += 1
                for s, amount in shares.items():
                    payouts[s] += amount
                pots.append({**pot, "winners": self.odd_chip_order(winners), "shares": shares})
            reason = "showdown"
        for seat, amount in payouts.items():
            self.stacks[seat] += amount
        for seat in self.seats:
            self.total_bets[seat] = 0
            self.street_bets[seat] = 0
        self.current_bet = 0
        self.turn = None
        self.hand_over = True
        self.result = {
            "reason": reason, "pots": pots, "payouts": payouts,
            "hands": {s: HAND_NAMES[ranks[s][0]] for s in ranks},
            "rankValues": ranks,
        }
        if reason == "showdown":
            self.street = "showdown"
        else:
            self.street = "complete"
        self._check_conservation()

    def _check_conservation(self):
        if any(v < 0 for v in self.stacks.values()):
            raise AssertionError("negative stack")
        total = sum(self.stacks.values()) + (0 if self.hand_over else sum(self.total_bets.values()))
        if total != self.initial_chips:
            raise AssertionError(f"chip conservation failed: {total} != {self.initial_chips}")


def next_button(previous, participants):
    """Moving button: the first participant clockwise after the previous button (house rule)."""
    group = sorted(participants)
    if previous is None:
        return group[0]
    later = [s for s in group if s > previous]
    return later[0] if later else group[0]


def build_pots(contributions, live, all_in=None):
    """Main pot then side pots from {seat: chips put in}; folded seats' chips count, only `live` seats are eligible.

    all_in=None: settlement (unmatched chips already returned), every live level splits a pot.
    all_in=set : a betting round still in progress (screen display). Only all-in players cap a pot;
    chips above the last all-in form one open pot that every live, not-all-in seat can still win.
    """
    live = sorted(live)
    top_any = max(contributions.values(), default=0)
    if top_any <= 0:
        return []
    levels = sorted({contributions[s] for s in live if contributions.get(s, 0) > 0 and (all_in is None or s in all_in)})
    if not levels or levels[-1] < top_any:
        levels.append(top_any)  # chips above every capped level
    result, previous = [], 0
    for level in levels:
        amount = sum(min(c, level) - min(c, previous) for c in contributions.values())
        eligible = [s for s in live if contributions.get(s, 0) >= level or (all_in is not None and s not in all_in)]
        if amount > 0:
            if result and result[-1]["eligible"] == eligible:
                result[-1]["amount"] += amount
            else:
                result.append({"amount": amount, "eligible": eligible})
        previous = level
    return result
