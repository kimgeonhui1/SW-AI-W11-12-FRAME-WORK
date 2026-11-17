"""2-4 seat engine (table.py). Every expected chip amount is worked out by hand in the comments."""
import random
import unittest

from engine import RANKS, SUITS, RuleError
from table import TableHand, build_pots, next_button

FULL = [r + s for r in RANKS for s in SUITS]


def deck(*prefix):
    return list(prefix) + [c for c in FULL if c not in prefix]


def play(hand, *steps):
    """steps: (seat, action[, to]) in the order the table must ask for them."""
    for step in steps:
        seat, action, *rest = step
        assert hand.turn == seat, f"expected seat {seat} to act, table says {hand.turn} (before {step})"
        hand.act(seat, action, *rest)


class OrderAndBlinds(unittest.TestCase):
    def test_heads_up_button_is_small_blind_acts_first_preflop_last_after(self):
        h = TableHand({0: 1000, 1: 1000}, button=0)
        self.assertEqual((h.sb, h.bb, h.turn), (0, 1, 0))
        self.assertEqual((h.stacks[0], h.stacks[1]), (990, 980))
        play(h, (0, "call"), (1, "check"))
        self.assertEqual((h.street, h.turn), ("flop", 1))  # big blind first after the flop
        play(h, (1, "check"), (0, "check"))
        self.assertEqual(h.street, "turn")

    def test_three_handed_order_button_first_preflop_small_blind_first_after(self):
        h = TableHand({0: 1000, 1: 1000, 2: 1000}, button=0)
        self.assertEqual((h.sb, h.bb, h.turn), (1, 2, 0))  # 3-handed: the button is under the gun
        play(h, (0, "call"), (1, "call"), (2, "check"))
        self.assertEqual((h.street, h.turn), ("flop", 1))
        play(h, (1, "fold"))
        self.assertEqual(h.turn, 2)  # folded seats are skipped
        play(h, (2, "check"), (0, "check"))
        self.assertEqual((h.street, h.turn), ("turn", 2))

    def test_four_handed_order_and_empty_seats_are_skipped(self):
        h = TableHand({0: 1000, 2: 1000, 3: 1000}, button=3, max_seats=4)  # seat 1 empty
        self.assertEqual((h.sb, h.bb, h.turn), (0, 2, 3))
        h = TableHand({0: 1000, 1: 1000, 2: 1000, 3: 1000}, button=1)
        self.assertEqual((h.sb, h.bb, h.turn), (2, 3, 0))  # under the gun is left of the big blind

    def test_deal_starts_left_of_the_button(self):
        d = deck("2♣", "3♣", "4♣", "5♣", "6♣", "7♣")
        h = TableHand({0: 100, 1: 100, 2: 100}, button=0, deck=d)
        self.assertEqual((h.holes[1], h.holes[2], h.holes[0]), (["2♣", "5♣"], ["3♣", "6♣"], ["4♣", "7♣"]))
        h = TableHand({0: 100, 1: 100}, button=0, deck=d)
        self.assertEqual((h.holes[1], h.holes[0]), (["2♣", "4♣"], ["3♣", "5♣"]))  # heads-up: big blind first

    def test_moving_button(self):
        self.assertEqual(next_button(None, [2, 0, 3]), 0)
        self.assertEqual(next_button(0, [0, 2, 3]), 2)
        self.assertEqual(next_button(3, [0, 2, 3]), 0)
        self.assertEqual(next_button(1, [0, 2, 3]), 2)  # previous button left: next participant after that seat

    def test_short_big_blind_still_sets_a_full_big_blind_to_call(self):
        # BB has 15. Button calls 20, SB completes to 20. Main 15x3 = 45 (all), side 5x2 = 10 (button, SB).
        h = TableHand({0: 1000, 1: 1000, 2: 15}, button=0)
        self.assertEqual((h.stacks[2], h.to_call(0)), (0, 20))
        play(h, (0, "call"), (1, "call"))
        self.assertEqual(h.street, "flop")
        self.assertEqual(h.pots(), [{"amount": 45, "eligible": [0, 1, 2]}, {"amount": 10, "eligible": [0, 1]}])


class RaisesAndReopening(unittest.TestCase):
    def test_minimum_raise_tracks_the_last_full_raise(self):
        h = TableHand({0: 1000, 1: 1000, 2: 1000}, button=0)
        self.assertEqual(h.raise_bounds(0), (40, 1000))
        with self.assertRaises(RuleError):
            h.act(0, "raise", 39)
        play(h, (0, "raise", 100))  # raise of 80
        self.assertEqual(h.raise_bounds(1), (180, 1000))
        with self.assertRaises(RuleError):
            h.act(1, "raise", 179)
        play(h, (1, "raise", 180))
        self.assertEqual(h.raise_bounds(2), (260, 1000))

    def test_short_all_in_does_not_reopen_raising_for_players_who_acted(self):
        # stacks 0:1000 1:1000 2:130, button 0 (UTG), SB 1, BB 2 (110 behind)
        h = TableHand({0: 1000, 1: 1000, 2: 130}, button=0)
        play(h, (0, "raise", 100), (1, "call"), (2, "all_in"))  # 130 total = +30, short of the 80 minimum
        self.assertEqual(h.turn, 0)
        self.assertEqual(h.legal_actions(0), ["fold", "call"])
        with self.assertRaises(RuleError):
            h.act(0, "raise", 300)
        play(h, (0, "call"))
        self.assertEqual(h.legal_actions(1), ["fold", "call"])
        play(h, (1, "call"))
        self.assertEqual(h.street, "flop")
        self.assertEqual(h.pots(), [{"amount": 390, "eligible": [0, 1, 2]}])

    def test_two_short_all_ins_that_add_up_to_a_full_raise_reopen_raising(self):
        # 0:1000 (button) 1:150 (SB) 2:200 (BB) 3:1000 (UTG)
        h = TableHand({0: 1000, 1: 150, 2: 200, 3: 1000}, button=0)
        play(h, (3, "raise", 100), (0, "call"), (1, "all_in"))  # 150: +50, short
        self.assertEqual(h.turn, 2)
        play(h, (2, "all_in"))  # 200: +50 again, short on its own
        self.assertEqual(h.turn, 3)
        # seat 3 last acted at 100 and now faces 200: +100 >= the 80 minimum, so raising is open again
        self.assertIn("raise", h.legal_actions(3))
        self.assertEqual(h.raise_bounds(3), (280, 1000))

    def test_all_in_for_less_than_the_call_is_a_call(self):
        h = TableHand({0: 1000, 1: 60, 2: 1000}, button=0)
        play(h, (0, "raise", 200))
        self.assertEqual(h.legal_actions(1), ["fold", "call", "all_in"])
        play(h, (1, "all_in"))  # 60 total, cannot match 200
        self.assertEqual((h.current_bet, h.turn), (200, 2))


class Settlement(unittest.TestCase):
    def test_stacks_100_200_300_400_all_in_three_side_pots_different_winners(self):
        # button 0, SB 1, BB 2, UTG 3. Deal order 1,2,3,0.
        # seat0 A♠A♥, seat1 K♠K♥, seat2 Q♠Q♥, seat3 4♣5♥; board 2♣ 7♦ 9♥ J♠ 3♦.
        # contributions 100/200/300/400 -> 100 of seat 3 is unmatched and returned.
        # main 100x4 = 400 (all) -> seat0; side1 100x3 = 300 (1,2,3) -> seat1; side2 100x2 = 200 (2,3) -> seat2.
        d = deck("K♠", "Q♠", "4♣", "A♠", "K♥", "Q♥", "5♥", "A♥", "8♣", "2♣", "7♦", "9♥", "8♦", "J♠", "8♥", "3♦")
        h = TableHand({0: 100, 1: 200, 2: 300, 3: 400}, button=0, deck=d)
        play(h, (3, "all_in"), (0, "all_in"), (1, "all_in"), (2, "all_in"))
        self.assertTrue(h.hand_over)
        self.assertEqual(h.board, ["2♣", "7♦", "9♥", "J♠", "3♦"])
        self.assertEqual(h.returns, [{"seat": 3, "amount": 100, "street": "preflop"}])
        pots = [(p["amount"], p["eligible"], p["winners"]) for p in h.result["pots"]]
        self.assertEqual(pots, [(400, [0, 1, 2, 3], [0]), (300, [1, 2, 3], [1]), (200, [2, 3], [2])])
        self.assertEqual(h.stacks, {0: 400, 1: 300, 2: 200, 3: 100})

    def test_folded_contributions_stay_in_the_pot_and_board_runs_out(self):
        # 4 x 300. button 0, SB 1, BB 2, UTG 3. UTG raises to 60, button calls, SB folds (10 dead),
        # BB shoves 300, UTG calls all-in, button folds (60 dead). One pot: 60+10+300+300 = 670 for 2 or 3.
        # seat2 Q♠Q♥ beats seat3 4♣5♥ on 2♣ 7♦ 9♥ J♠ 3♦.
        d = deck("K♠", "Q♠", "4♣", "A♠", "K♥", "Q♥", "5♥", "A♥", "8♣", "2♣", "7♦", "9♥", "8♦", "J♠", "8♥", "3♦")
        h = TableHand({0: 300, 1: 300, 2: 300, 3: 300}, button=0, deck=d)
        play(h, (3, "raise", 60), (0, "call"), (1, "fold"), (2, "all_in"), (3, "call"), (0, "fold"))
        self.assertTrue(h.hand_over)
        self.assertEqual(len(h.board), 5)
        self.assertEqual([(p["amount"], p["eligible"], p["winners"]) for p in h.result["pots"]], [(670, [2, 3], [2])])
        self.assertEqual(h.stacks, {0: 240, 1: 290, 2: 670, 3: 0})

    def test_tie_with_odd_chip_goes_left_of_the_button(self):
        # 3 x 1000, button 0, SB 1, BB 2. Pre-flop everyone puts 20; flop seat1 bets 25, both call -> 135.
        # Board A♠ A♦ K♣ K♥ 2♠: seat1 Q♠3♦ and seat2 Q♥4♦ both play AAKKQ, seat0 J♠5♦ has AAKKJ.
        # 135 split two ways: 67 each, odd chip to seat1 (first winner left of the button): 68/67.
        d = deck("Q♠", "Q♥", "J♠", "3♦", "4♦", "5♦", "6♣", "A♠", "A♦", "K♣", "6♦", "K♥", "6♥", "2♠")
        h = TableHand({0: 1000, 1: 1000, 2: 1000}, button=0, deck=d)
        play(h, (0, "call"), (1, "call"), (2, "check"), (1, "bet", 25), (2, "call"), (0, "call"))
        play(h, (1, "check"), (2, "check"), (0, "check"), (1, "check"), (2, "check"), (0, "check"))
        self.assertEqual(h.result["pots"][0]["shares"], {1: 68, 2: 67})
        self.assertEqual(h.stacks, {0: 955, 1: 1023, 2: 1022})

    def test_split_side_pot_while_main_pot_has_a_single_winner(self):
        # 0:100 (button), 1:500 (SB), 2:500 (BB). Button shoves 100, SB and BB call; flop SB bets 200, BB calls,
        # then both check down. Board 2♣ 7♦ 9♥ J♠ 3♦: seat0 A♠A♥ wins main 300; seats 1 and 2 hold K♠K♥ / K♦K♣
        # and split the side pot 400 -> 200 each.
        d = deck("K♠", "K♦", "A♠", "K♥", "K♣", "A♥", "8♣", "2♣", "7♦", "9♥", "8♦", "J♠", "8♥", "3♦")
        h = TableHand({0: 100, 1: 500, 2: 500}, button=0, deck=d)
        play(h, (0, "all_in"), (1, "call"), (2, "call"))
        play(h, (1, "bet", 200), (2, "call"), (1, "check"), (2, "check"), (1, "check"), (2, "check"))
        pots = [(p["amount"], p["eligible"], p["shares"]) for p in h.result["pots"]]
        self.assertEqual(pots, [(300, [0, 1, 2], {0: 300}), (400, [1, 2], {1: 200, 2: 200})])
        self.assertEqual(h.stacks, {0: 300, 1: 400, 2: 400})

    def test_everyone_folds_to_a_bet_and_the_unmatched_bet_returns(self):
        h = TableHand({0: 1000, 1: 1000, 2: 1000, 3: 1000}, button=0)
        play(h, (3, "raise", 300), (0, "fold"), (1, "fold"), (2, "fold"))
        # seat 3's 300 is matched by nobody above the BB's 20: 280 returns; pot 20 + 10 + 20 = 50
        self.assertEqual(h.result["reason"], "fold")
        self.assertEqual(h.stacks, {0: 1000, 1: 990, 2: 980, 3: 1030})


class LivePots(unittest.TestCase):
    def test_blinds_and_uncalled_bets_are_one_open_pot(self):
        self.assertEqual(build_pots({0: 0, 1: 10, 2: 20, 3: 0}, [0, 1, 2, 3], set()), [{"amount": 30, "eligible": [0, 1, 2, 3]}])
        self.assertEqual(build_pots({0: 0, 1: 0}, [0, 1], set()), [])

    def test_only_all_in_players_cap_a_pot_while_betting_continues(self):
        # seat 0 all-in for 100, seats 1 and 2 at 300 so far, seat 3 folded after 50
        live = build_pots({0: 100, 1: 300, 2: 300, 3: 50}, [0, 1, 2], {0})
        self.assertEqual(live, [{"amount": 350, "eligible": [0, 1, 2]}, {"amount": 400, "eligible": [1, 2]}])
        # seat 2 has not called the raise yet: still eligible for the open pot
        self.assertEqual(build_pots({0: 100, 1: 300, 2: 120}, [0, 1, 2], {0}),
                         [{"amount": 300, "eligible": [0, 1, 2]}, {"amount": 220, "eligible": [1, 2]}])

    def test_live_view_matches_settlement_once_the_round_is_closed(self):
        hand = TableHand({0: 100, 1: 200, 2: 1000}, button=0, deck=deck())
        hand.act(0, "all_in")
        hand.act(1, "all_in")
        self.assertEqual(hand.live_pots(), [{"amount": 220, "eligible": [0, 1, 2]}, {"amount": 100, "eligible": [1, 2]}])
        hand.act(2, "call")
        self.assertEqual([(p["amount"], p["eligible"]) for p in hand.result["pots"]], [(300, [0, 1, 2]), (200, [1, 2])])


class RandomConservation(unittest.TestCase):
    def test_random_hands_keep_chips_and_cards_consistent(self):
        rng = random.Random(4242)
        for _ in range(400):
            n = rng.choice([2, 3, 4])
            seats = sorted(rng.sample(range(4), n))
            stacks = {s: rng.choice([5, 15, 40, 100, 333, 1000]) for s in seats}
            h = TableHand(stacks, button=rng.choice(seats), deck=rng.sample(FULL, 52))
            total = sum(stacks.values())
            cards = [c for s in seats for c in h.holes[s]]
            self.assertEqual(len(set(cards)), 2 * n)
            while not h.hand_over:
                legal = h.legal_actions(h.turn)
                action = rng.choice(legal)
                to = None
                if action in ("bet", "raise"):
                    low, high = h.raise_bounds(h.turn)
                    to = rng.choice([low, high, rng.randint(low, high)])
                h.act(h.turn, action, to)
                self.assertEqual(sum(h.stacks.values()) + sum(h.total_bets.values()), total)
            self.assertEqual(sum(h.stacks.values()), total)
            self.assertTrue(all(v >= 0 for v in h.stacks.values()))
            self.assertEqual(sum(h.result["payouts"].values()), sum(p["amount"] for p in h.result["pots"]))
            self.assertEqual(len(set(cards + h.board)), 2 * n + len(h.board))


if __name__ == "__main__":
    unittest.main()
