import unittest

from app.services import minigame_service


class MiniGameServiceTests(unittest.TestCase):
    def setUp(self):
        self.original_words = minigame_service.WORDS
        minigame_service.WORDS = (('无畏契约', '战术射击游戏'),)
        minigame_service._sessions.clear()

    def tearDown(self):
        minigame_service.WORDS = self.original_words
        minigame_service._sessions.clear()

    def test_hangman_guess_letter_then_word(self):
        start = minigame_service.start_game('chan-1', 'user-1', 'Tester#1', '猜词')
        self.assertTrue(start['ok'])
        self.assertIn('猜词', start['message'])
        self.assertIn('提示', start['message'])
        self.assertIn('字数: **4**', start['message'])
        self.assertIn('操作: `/游戏 猜 内容`', start['message'])

        letter = minigame_service.handle_guess('chan-1', 'user-1', '无')
        self.assertTrue(letter['ok'])
        self.assertIn('无 _ _ _', letter['message'])

        win = minigame_service.handle_guess('chan-1', 'user-1', '无畏契约')
        self.assertTrue(win['ended'])
        self.assertEqual(win['record']['result'], 'win')
        self.assertNotIn(('chan-1', 'user-1'), minigame_service._sessions)

    def test_scramble_correct_answer_ends_session(self):
        start = minigame_service.start_game('chan-1', 'user-1', 'Tester#1', '乱序')
        self.assertTrue(start['ok'])
        self.assertIn('提示', start['message'])
        self.assertIn('字数: **4**', start['message'])
        self.assertIn('操作: `/游戏 猜 内容`', start['message'])

        wrong = minigame_service.handle_guess('chan-1', 'user-1', '老板')
        self.assertFalse(wrong['ended'])
        self.assertIn('没对', wrong['message'])

        win = minigame_service.handle_guess('chan-1', 'user-1', '无畏契约')
        self.assertTrue(win['ended'])
        self.assertIn('还原成功', win['message'])
        self.assertEqual(win['record']['game'], 'scramble')

    def test_default_chinese_word_bank_has_hints_and_role_terms(self):
        words = []
        for item in self.original_words:
            word, hint = minigame_service._word_entry(item)
            words.append(word)
            self.assertGreaterEqual(len(word), 1)
            self.assertTrue(hint)
        self.assertEqual(len(words), len(set(words)))
        self.assertGreaterEqual(len(words), 120)
        self.assertIn('三角洲行动', words)
        self.assertIn('烽火地带', words)
        self.assertIn('全面战场', words)
        self.assertIn('红狼', words)
        self.assertIn('蜂医', words)
        self.assertIn('牧羊人', words)
        self.assertIn('蝶', words)
        self.assertIn('飞将', words)
        self.assertIn('幻影', words)
        self.assertIn('捷风', words)
        self.assertIn('零', words)
        self.assertNotIn('飞将狙击', words)
        self.assertNotIn('幻影步枪', words)
        self.assertNotIn('捷风突破', words)

    def test_one_character_role_words_can_be_selected(self):
        minigame_service.WORDS = (('蝶', '悄悄贴近后打关键一手的角色'),)
        minigame_service._sessions.clear()

        start = minigame_service.start_game('chan-1', 'user-1', 'Tester#1', '猜词')
        self.assertTrue(start['ok'])
        self.assertIn('字数: **1**', start['message'])

        win = minigame_service.handle_guess('chan-1', 'user-1', '蝶')
        self.assertTrue(win['ended'])
        self.assertEqual(win['record']['result'], 'win')

    def test_mastermind_accepts_chinese_color_guess(self):
        start = minigame_service.start_game('chan-1', 'user-1', 'Tester#1', '密码')
        self.assertIn('操作: `/游戏 猜 内容`', start['message'])
        session = minigame_service._sessions[('chan-1', 'user-1')]
        session.state['code'] = ['red', 'blue', 'green', 'yellow']

        win = minigame_service.handle_guess('chan-1', 'user-1', '红 蓝 绿 黄')
        self.assertTrue(win['ended'])
        self.assertIn('密码破译成功', win['message'])

    def test_blackjack_stand_ends_session(self):
        start = minigame_service.start_game('chan-1', 'user-1', 'Tester#1', '21点')
        self.assertTrue(start['ok'])
        self.assertIn('21 点', start['message'])

        result = minigame_service.handle_blackjack_action('chan-1', 'user-1', '停牌')
        self.assertTrue(result['ended'])
        self.assertNotIn(('chan-1', 'user-1'), minigame_service._sessions)

    def test_requires_quit_before_starting_another_game(self):
        minigame_service.start_game('chan-1', 'user-1', 'Tester#1', '猜词')
        blocked = minigame_service.start_game('chan-1', 'user-1', 'Tester#1', '21点')
        self.assertFalse(blocked['ok'])
        self.assertIn('正在进行', blocked['message'])

        quit_result = minigame_service.quit_game('chan-1', 'user-1')
        self.assertTrue(quit_result['ok'])

    def test_connect4_requires_two_players_and_turn_order(self):
        missing = minigame_service.start_connect4('chan-1', 'user-1', 'Tester#1', '', '')
        self.assertFalse(missing['ok'])

        start = minigame_service.start_connect4('chan-1', 'user-1', 'Tester#1', 'user-2', 'Other#2')
        self.assertTrue(start['ok'])
        session = minigame_service._sessions[('connect4', 'chan-1')]
        session.state['turn'] = 0

        blocked = minigame_service.handle_connect4_move('chan-1', 'user-2', '1')
        self.assertFalse(blocked['ok'])
        self.assertIn('还没轮到你', blocked['message'])

        moved = minigame_service.handle_connect4_move('chan-1', 'user-1', '1')
        self.assertTrue(moved['ok'])
        self.assertIn('当前回合: (met)user-2(met)', moved['message'])

    def test_connect4_horizontal_win_ends_session(self):
        minigame_service.start_connect4('chan-1', 'user-1', 'Tester#1', 'user-2', 'Other#2')
        session = minigame_service._sessions[('connect4', 'chan-1')]
        session.state['turn'] = 0

        moves = [
            ('user-1', '1'),
            ('user-2', '1'),
            ('user-1', '2'),
            ('user-2', '2'),
            ('user-1', '3'),
            ('user-2', '3'),
        ]
        for user_id, column in moves:
            result = minigame_service.handle_connect4_move('chan-1', user_id, column)
            self.assertFalse(result['ended'])

        win = minigame_service.handle_connect4_move('chan-1', 'user-1', '4')
        self.assertTrue(win['ended'])
        self.assertIn('连成四子', win['message'])
        self.assertNotIn(('connect4', 'chan-1'), minigame_service._sessions)


if __name__ == '__main__':
    unittest.main()
