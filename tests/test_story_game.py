import json
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.story_game import (
    StoryCharacterRelation,
    StoryDirectMessage,
    StoryMemoryFragment,
    StoryPlayerState,
    StoryTurnLog,
)
from app.models.user import User
from app.services import story_game_service


class StoryGameTestConfig(Config):
    TESTING = True
    SECRET_KEY = 'test-secret'
    KOOK_BOT_ENABLED = False
    KOOK_TOKEN = 'your-kook-bot-token'
    PUBLIC_SITE_URL = 'http://localhost'
    SITE_URL = 'http://localhost'
    STORY_LLM_API_KEY = ''
    STORY_LLM_MODEL = 'deepseek-ai/DeepSeek-V4-Flash'


class StoryGameTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.db_path = path

        StoryGameTestConfig.SQLALCHEMY_DATABASE_URI = f'sqlite:///{self.db_path}'
        self.app = create_app(StoryGameTestConfig, start_background_tasks=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.user = User(
            username='story_user',
            role='god',
            nickname='剧情玩家',
            kook_id='story-1',
            kook_username='Story#1',
            kook_bound=True,
            status=True,
            register_type='manual',
        )
        self.user.set_password('password')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def start_story(self):
        return story_game_service.start_story(
            kook_id='story-1',
            kook_username='Story#1',
            user_id=self.user.id,
            world_arg='1',
            background_arg='1',
        )

    def test_start_without_args_shows_menu(self):
        result = story_game_service.start_story('story-2', 'Story#2', None)

        self.assertFalse(result['ok'])
        self.assertIn('/story start 1 1', result['message'])
        self.assertEqual(StoryPlayerState.query.count(), 0)

    def test_start_creates_state_relations_and_initial_memory(self):
        result = self.start_story()

        self.assertTrue(result['ok'])
        self.assertIn('Chapter 0', result['message'])
        self.assertEqual(StoryPlayerState.query.count(), 1)
        self.assertEqual(StoryCharacterRelation.query.count(), 5)
        memory = StoryMemoryFragment.query.filter_by(memory_id='memory_01_number_07').first()
        self.assertIsNotNone(memory)
        self.assertEqual(memory.title, '编号 07')

    def test_continue_without_llm_key_uses_fallback_and_persists_turn(self):
        self.start_story()

        result = story_game_service.continue_story(
            kook_id='story-1',
            user_id=self.user.id,
            user_input='我举起手，说我不记得自己是谁。',
            channel_id='chan-1',
        )

        self.assertTrue(result['ok'])
        self.assertFalse(result['llm_used'])
        self.assertIn('捷风', result['message'])
        self.assertEqual(StoryTurnLog.query.count(), 1)
        self.assertEqual(StoryDirectMessage.query.filter_by(character_id='jett').count(), 1)

    def test_invalid_llm_json_falls_back(self):
        self.start_story()
        original = story_game_service._call_story_llm
        story_game_service._call_story_llm = lambda messages: '这不是 JSON'
        try:
            result = story_game_service.continue_story(
                kook_id='story-1',
                user_id=self.user.id,
                user_input='我试着跟捷风解释。',
            )
        finally:
            story_game_service._call_story_llm = original

        self.assertTrue(result['ok'])
        self.assertFalse(result['llm_used'])
        self.assertEqual(StoryTurnLog.query.count(), 1)

    def test_relationship_delta_is_clamped_and_profile_hides_raw_trust(self):
        self.start_story()
        payload = {
            'visible_text': '捷风看了你一眼，暂时放低了枪口。',
            'state_updates': {
                'relationship_changes': {
                    'jett': {'trust_delta': 999, 'bond_event': 'huge_delta_should_clamp'},
                },
            },
            'suggested_choices': ['跟上捷风'],
        }
        original = story_game_service._call_story_llm
        story_game_service._call_story_llm = lambda messages: json.dumps(payload, ensure_ascii=False)
        try:
            result = story_game_service.continue_story(
                kook_id='story-1',
                user_id=self.user.id,
                user_input='我选择相信她。',
            )
        finally:
            story_game_service._call_story_llm = original

        relation = StoryCharacterRelation.query.filter_by(kook_id='story-1', character_id='jett').first()
        profile = story_game_service.profile_text('story-1')

        self.assertTrue(result['llm_used'])
        self.assertEqual(relation.trust, 24)
        self.assertNotIn('trust', profile.lower())
        self.assertNotIn('24', profile)
        self.assertIn('捷风', profile)

    def test_archive_lists_memory_fragments(self):
        self.start_story()

        archive = story_game_service.archive_text('story-1')

        self.assertIn('编号 07', archive)
        self.assertIn('手腕', archive)

    def test_lore_reference_retrieves_agents_maps_and_weapons(self):
        self.start_story()
        state = StoryPlayerState.query.filter_by(kook_id='story-1').first()

        messages = story_game_service._build_story_messages(
            state,
            '我想去训练场，拿一把鬼魅，问雷兹为什么这么喜欢爆破。',
        )
        prompt = messages[1]['content']

        self.assertIn('【角色参考】雷兹 / Raze', prompt)
        self.assertIn('【地图参考】训练场 / Range', prompt)
        self.assertIn('【武器参考】鬼魅 / Ghost', prompt)

    def test_deepseek_base_url_and_default_model_are_normalized(self):
        self.assertEqual(
            story_game_service._normalize_story_api_url('https://api.deepseek.com'),
            'https://api.deepseek.com/chat/completions',
        )
        self.assertEqual(
            story_game_service._normalize_story_model(
                'deepseek-ai/DeepSeek-V4-Flash',
                'https://api.deepseek.com/chat/completions',
            ),
            'deepseek-chat',
        )

    def test_dm_reply_marks_message_and_updates_relation(self):
        self.start_story()
        story_game_service.continue_story(
            kook_id='story-1',
            user_id=self.user.id,
            user_input='我告诉捷风，我会跟上她。',
        )
        before = StoryCharacterRelation.query.filter_by(kook_id='story-1', character_id='jett').first().trust

        result = story_game_service.reply_dm(
            kook_id='story-1',
            user_id=self.user.id,
            character_arg='捷风',
            reply_text='你这是在担心我吗？',
        )

        latest_original = (
            StoryDirectMessage.query
            .filter_by(kook_id='story-1', character_id='jett', trigger_event='chapter_0_training_invite')
            .first()
        )
        after = StoryCharacterRelation.query.filter_by(kook_id='story-1', character_id='jett').first().trust

        self.assertTrue(result['ok'])
        self.assertIsNotNone(latest_original.replied_at)
        self.assertGreater(after, before)
        self.assertIn('私信 / 捷风', result['message'])


if __name__ == '__main__':
    unittest.main()
