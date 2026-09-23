from __future__ import annotations

import unittest

from archeon.context import ContextBudgetManager, ContextOptimizer, ConversationMemory, ResponseBudgetManager


class ContextBudgetTests(unittest.TestCase):
    def test_keeps_static_system_and_current_user_while_dropping_old_context(self) -> None:
        recent = tuple({"role": "user", "content": "x" * 300} for _ in range(10))
        result = ContextBudgetManager().build(
            system="stable system", user="current question",
            recent_conversation=recent, max_prompt_tokens=300,
        )
        self.assertEqual(result.messages[0]["content"], "stable system")
        self.assertEqual(result.messages[-1]["content"], "current question")
        self.assertGreater(result.recent_messages_dropped, 0)
        self.assertLessEqual(result.estimated_tokens, 300)

    def test_memory_is_bounded_and_can_be_disabled_by_requesting_zero_turns(self) -> None:
        memory = ConversationMemory(max_messages=4)
        for index in range(5):
            memory.add_turn(f"u{index}", f"a{index}")
        self.assertEqual(len(memory.recent(2)), 4)
        self.assertEqual(memory.recent(0), ())
        memory.clear()
        self.assertEqual(memory.recent(2), ())

    def test_optimizer_deduplicates_and_bounds_large_turns(self) -> None:
        messages = ({"role": "user", "content": "hola"}, {"role": "user", "content": " hola "}, {"role": "assistant", "content": "x" * 3000})
        optimized = ContextOptimizer().optimize(messages, per_message_tokens=100)
        self.assertEqual(len(optimized), 2)
        self.assertLessEqual(len(optimized[-1]["content"]), 305)

    def test_response_budget_is_multilingual_and_intent_based(self) -> None:
        manager = ResponseBudgetManager()
        self.assertEqual(manager.allocate("Responde solo el nombre", configured_max=512).max_tokens, 64)
        self.assertEqual(manager.allocate("اشرح بالتفصيل", configured_max=512).mode, "detailed")
        self.assertEqual(manager.allocate("请只回答名称", configured_max=512).mode, "concise")


if __name__ == "__main__":
    unittest.main()
