import unittest

from engine import PokerEngine, RuleError, best_hand, evaluate_five, new_deck


def deck_with_prefix(*prefix):
    full = [rank + suit for rank in "23456789TJQKA" for suit in ("♠", "♥", "♦", "♣")]
    return list(prefix) + [card for card in full if card not in prefix]


class EvaluatorTests(unittest.TestCase):
    def test_shuffled_deck_contains_each_standard_card_once(self):
        deck = new_deck()
        self.assertEqual(len(deck), 52)
        self.assertEqual(len(set(deck)), 52)

    def test_wheel_straight_is_five_high(self):
        self.assertEqual(evaluate_five(["A♠", "2♥", "3♦", "4♣", "5♠"]), (4, 5))

    def test_seven_card_best_five_and_kickers(self):
        rank, cards = best_hand(["A♠", "A♥", "K♦", "K♣", "Q♠", "2♥", "3♦"])
        self.assertEqual(rank, (2, 14, 13, 12))
        self.assertEqual(len(cards), 5)

    def test_categories_order_correctly(self):
        straight_flush = evaluate_five(["9♠", "T♠", "J♠", "Q♠", "K♠"])
        four_kind = evaluate_five(["A♠", "A♥", "A♦", "A♣", "K♠"])
        self.assertGreater(straight_flush, four_kind)

    def test_all_nine_five_card_categories_order(self):
        hands = [
            ["A♠", "K♥", "Q♦", "9♣", "3♠"],
            ["A♠", "A♥", "K♦", "Q♣", "9♠"],
            ["K♠", "K♥", "Q♦", "Q♣", "A♠"],
            ["K♠", "K♥", "K♦", "A♣", "Q♠"],
            ["5♠", "4♥", "3♦", "2♣", "A♠"],
            ["A♠", "J♠", "8♠", "4♠", "2♠"],
            ["A♠", "A♥", "A♦", "K♣", "K♠"],
            ["A♠", "A♥", "A♦", "A♣", "K♠"],
            ["9♠", "T♠", "J♠", "Q♠", "K♠"],
        ]
        ranks = [evaluate_five(hand) for hand in hands]
        self.assertEqual([rank[0] for rank in ranks], list(range(9)))
        self.assertEqual(ranks, sorted(ranks))


class HoldemEngineTests(unittest.TestCase):
    def make_engine(self, stacks=None, deck=None):
        return PokerEngine(starting_stacks=stacks, deck_factory=lambda: list(deck or deck_with_prefix()))

    def check_through_showdown(self, engine):
        if engine.turn == "human":
            engine.act("human", "call" if engine._to_call("human") else "check")
        if engine.turn == "bot":
            engine.act("bot", "check" if engine._to_call("bot") == 0 else "call")
        for _ in range(3):
            if engine.hand_over:
                break
            if engine.turn == "bot":
                engine.act("bot", "check")
            if engine.turn == "human":
                engine.act("human", "check")

    def test_blinds_button_and_big_blind_option(self):
        engine = self.make_engine()
        state = engine.start_hand()
        self.assertEqual((state["button"], state["turn"], state["pot"], state["humanStack"], state["botStack"]),
                         ("human", "human", 30, 990, 980))
        self.assertEqual(state["humanCards"], state["humanCards"][:2])
        engine.act("human", "call")
        self.assertEqual(engine.turn, "bot")  # BB still has its preflop option
        engine.act("bot", "check")
        self.assertEqual((engine.phase, engine.turn, len(engine.snapshot()["board"])), ("flop", "bot", 3))

    def test_turn_order_check_call_and_all_streets(self):
        engine = self.make_engine()
        engine.start_hand()
        self.check_through_showdown(engine)
        state = engine.snapshot()
        self.assertTrue(state["handOver"])
        self.assertEqual((state["phase"], len(state["board"])), ("showdown", 5))
        self.assertIsNotNone(state["result"])
        self.assertEqual(state["humanStack"] + state["botStack"], 2000)

    def test_server_side_showdown_reveals_only_after_completion(self):
        deck = deck_with_prefix("A♠", "2♦", "K♠", "3♦", "4♥", "Q♠", "J♠", "T♠", "6♥", "4♦", "7♥", "5♥")
        engine = self.make_engine(deck=deck)
        state = engine.start_hand()
        self.assertEqual((len(state["humanCards"]), state["botCards"], state["botCardsRevealed"]), (2, [], False))
        self.check_through_showdown(engine)
        state = engine.snapshot()
        self.assertEqual(state["result"]["winner"], "human")
        self.assertEqual(state["result"]["hands"]["human"], "스트레이트 플러시")
        self.assertTrue(state["botCardsRevealed"])

    def test_board_tie_splits_the_pot(self):
        deck = deck_with_prefix("2♦", "4♣", "3♦", "5♣", "6♥", "A♠", "K♠", "Q♠", "6♦", "J♠", "7♥", "T♠")
        engine = self.make_engine(deck=deck)
        engine.start_hand()
        self.check_through_showdown(engine)
        state = engine.snapshot()
        self.assertEqual(state["result"]["winner"], "tie")
        self.assertEqual(state["result"]["payouts"], {"human": 20, "bot": 20})
        self.assertEqual(state["humanStack"] + state["botStack"], 2000)

    def test_fold_returns_uncalled_chips_and_settles_once(self):
        engine = self.make_engine()
        engine.start_hand()
        engine.act("human", "raise", 40)
        state = engine.act("bot", "fold")
        self.assertEqual(state["result"], {"winner": "human", "reason": "fold", "pot": 40,
                                            "payouts": {"human": 40, "bot": 0}})
        self.assertEqual((state["humanStack"], state["botStack"], state["pot"]), (1020, 980, 0))
        with self.assertRaises(RuleError):
            engine.act("human", "check")

    def test_turn_stack_minimum_raise_and_action_reopen(self):
        engine = self.make_engine()
        engine.start_hand()
        with self.assertRaises(RuleError):
            engine.act("bot", "check")
        with self.assertRaises(RuleError):
            engine.act("human", "check")  # facing the big blind
        with self.assertRaises(RuleError):
            engine.act("human", "raise", 30)
        with self.assertRaises(RuleError):
            engine.act("human", "raise", 2000)
        engine.act("human", "raise", 40)
        engine.act("bot", "raise", 60)
        self.assertIn("raise", engine.legal_actions("human"))  # full raise reopened action
        engine.act("human", "call")
        self.assertEqual(engine.phase, "flop")

    def test_short_all_in_call_refunds_unmatched_raise_and_preserves_chips(self):
        deck = deck_with_prefix("A♠", "2♦", "K♠", "3♦", "4♥", "Q♠", "J♠", "T♠", "6♥", "4♦", "7♥", "5♥")
        engine = self.make_engine({"human": 1000, "bot": 35}, deck)
        engine.start_hand()
        engine.act("human", "raise", 40)
        state = engine.act("bot", "call")
        self.assertEqual((state["phase"], state["pot"], state["humanCommitted"], state["botCommitted"]),
                         ("showdown", 0, 0, 0))
        self.assertEqual(state["result"]["pot"], 70)
        self.assertEqual(state["result"]["winner"], "human")
        self.assertEqual(state["humanStack"] + state["botStack"], 1035)
        self.assertEqual(state["botStack"], 0)
        self.assertTrue(state["matchOver"])

    def test_short_all_in_raise_does_not_reopen_a_prior_actor(self):
        engine = self.make_engine({"human": 1000, "bot": 55})
        engine.start_hand()
        engine.act("human", "raise", 40)
        state = engine.act("bot", "all_in")
        self.assertEqual(state["turn"], "human")
        self.assertNotIn("raise", state["legalActions"])
        self.assertEqual(state["toCall"], 15)
        state = engine.act("human", "call")
        self.assertTrue(state["handOver"])
        self.assertEqual(state["result"]["pot"], 110)
        self.assertEqual(state["humanStack"] + state["botStack"], 1055)

    def test_short_all_in_call_is_not_misread_as_a_raise(self):
        engine = self.make_engine({"human": 25, "bot": 1000})
        engine.start_hand()
        engine.act("human", "call")
        engine.act("bot", "raise", 40)
        state = engine.act("human", "all_in")
        self.assertTrue(state["handOver"])
        self.assertEqual(state["result"]["pot"], 50)
        self.assertEqual(state["humanStack"] + state["botStack"], 1025)

    def test_all_in_blind_runs_out_without_a_fake_action(self):
        engine = self.make_engine({"human": 5, "bot": 100})
        state = engine.start_hand()
        self.assertTrue(state["handOver"])
        self.assertEqual((state["phase"], len(state["board"]), state["result"]["pot"]), ("showdown", 5, 10))
        self.assertEqual(state["humanStack"] + state["botStack"], 105)

    def test_next_hand_toggles_button_and_keeps_stack_total(self):
        engine = self.make_engine()
        engine.start_hand()
        engine.act("human", "fold")
        state = engine.start_hand()
        self.assertEqual(state["button"], "bot")
        self.assertEqual(state["turn"], "bot")
        self.assertEqual(state["humanStack"] + state["botStack"] + state["pot"], 2000)


if __name__ == "__main__":
    unittest.main()
