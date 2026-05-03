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
    StoryHardState,
    StoryMemoryFragment,
    StoryPlayerState,
    StoryTurnLog,
)
from app.models.user import User
from app.services import story_game_service, story_memory_service


class StoryGameTestConfig(Config):
    TESTING = True
    SECRET_KEY = 'test-secret'
    KOOK_BOT_ENABLED = False
    KOOK_TOKEN = 'your-kook-bot-token'
    PUBLIC_SITE_URL = 'http://localhost'
    SITE_URL = 'http://localhost'
    STORY_LLM_API_KEY = ''
    STORY_LLM_MODEL = 'deepseek-ai/DeepSeek-V4-Flash'
    STORY_LLM_MIN_VISIBLE_CHARS = 1
    STORY_DM_MIN_VISIBLE_CHARS = 1
    STORY_LANGGRAPH_ENABLED = True
    STORY_MEMORY_ENABLED = False


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
        hard = StoryHardState.query.filter_by(kook_id='story-1').first()
        self.assertIsNotNone(hard)
        self.assertEqual(hard.location_id, 'sealed_training_room')
        self.assertEqual(hard.mission_id, 'chapter_0_escape')
        memory = StoryMemoryFragment.query.filter_by(memory_id='memory_01_number_07').first()
        self.assertIsNotNone(memory)
        self.assertEqual(memory.title, '编号 07')

    def test_continue_without_llm_key_does_not_advance_story(self):
        self.start_story()

        result = story_game_service.continue_story(
            kook_id='story-1',
            user_id=self.user.id,
            user_input='我举起手，说我不记得自己是谁。',
            channel_id='chan-1',
        )

        self.assertFalse(result['ok'])
        self.assertFalse(result['llm_used'])
        self.assertIn('AI 剧情引擎没有成功返回内容', result['message'])
        self.assertEqual(StoryTurnLog.query.count(), 0)
        self.assertEqual(StoryDirectMessage.query.filter_by(character_id='jett').count(), 0)

    def test_invalid_llm_json_does_not_advance_story(self):
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

        self.assertFalse(result['ok'])
        self.assertFalse(result['llm_used'])
        self.assertIn('AI 剧情引擎没有成功返回内容', result['message'])
        self.assertEqual(StoryTurnLog.query.count(), 0)

    def test_invalid_story_payload_is_repaired_once(self):
        self.start_story()
        calls = []
        bad_payload = {'state_updates': {}, 'suggested_choices': []}
        good_payload = {
            'visible_text': '捷风压低枪口，示意你跟上她。走廊深处的红灯仍在闪烁。',
            'narrative_events': [
                {'type': 'scene_transition', 'summary': '玩家跟随捷风离开训练室', 'actor': 'jett'},
            ],
            'state_updates': {
                'current_scene': 'escape_corridor',
                'last_npc': 'jett',
                'summary': '玩家暂时跟随捷风离开训练室。',
            },
            'suggested_choices': ['继续跟随捷风', '询问编号 07'],
        }

        def fake_call(messages):
            calls.append(messages)
            return json.dumps(bad_payload if len(calls) == 1 else good_payload, ensure_ascii=False)

        original = story_game_service._call_story_llm
        story_game_service._call_story_llm = fake_call
        try:
            result = story_game_service.continue_story(
                kook_id='story-1',
                user_id=self.user.id,
                user_input='我跟着捷风离开训练室。',
            )
        finally:
            story_game_service._call_story_llm = original

        turn = StoryTurnLog.query.filter_by(kook_id='story-1').first()
        updates = json.loads(turn.state_updates)

        self.assertTrue(result['ok'])
        self.assertEqual(len(calls), 2)
        self.assertIn('visible_text 缺失或为空', calls[1][-1]['content'])
        self.assertEqual(updates['narrative_events'][0]['type'], 'scene_transition')

    def test_invalid_character_in_story_payload_is_rejected(self):
        self.start_story()
        payload = {
            'visible_text': '捷风看向你，空气里只剩下警报声。',
            'state_updates': {
                'relationship_changes': {
                    'unknown_npc': {'trust_delta': 2},
                },
            },
            'suggested_choices': [],
        }
        original = story_game_service._call_story_llm
        story_game_service._call_story_llm = lambda messages: json.dumps(payload, ensure_ascii=False)
        try:
            result = story_game_service.continue_story(
                kook_id='story-1',
                user_id=self.user.id,
                user_input='我试图和一个不存在的角色建立关系。',
            )
        finally:
            story_game_service._call_story_llm = original

        self.assertFalse(result['ok'])
        self.assertEqual(StoryTurnLog.query.count(), 0)

    def test_relationship_delta_is_clamped_and_profile_hides_raw_trust(self):
        self.start_story()
        payload = {
            'visible_text': '捷风看了你一眼，暂时放低了枪口。',
            'state_updates': {
                'relationship_changes': {
                    'jett': {'trust_delta': 999, 'bond_event': 'huge_delta_should_clamp'},
                },
            },
            'suggested_choices': ['1. 跟上捷风', 'A. 追问她'],
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
        self.assertEqual(StoryPlayerState.query.filter_by(kook_id='story-1').first().choice_list[0], '跟上捷风')

    def test_continue_story_runs_through_orchestrator_nodes(self):
        self.start_story()
        payload = {
            'visible_text': '捷风没有立刻回答，只是把通讯器推到你手边，让你自己听那段破碎广播。',
            'state_updates': {
                'summary': '玩家接触到第一段破碎广播，捷风开始观察玩家反应。',
            },
            'suggested_choices': ['监听广播', '询问捷风', '检查门口'],
        }
        original = story_game_service._call_story_llm
        story_game_service._call_story_llm = lambda messages: json.dumps(payload, ensure_ascii=False)
        try:
            result = story_game_service.continue_story(
                kook_id='story-1',
                user_id=self.user.id,
                user_input='我问捷风通讯器里是什么。',
            )
        finally:
            story_game_service._call_story_llm = original

        self.assertTrue(result['ok'])
        self.assertIn(result['orchestrator'], ('langgraph', 'sequential'))
        self.assertEqual(
            result['graph_trace'][:4],
            ['prepare_context', 'call_llm', 'validate_payload', 'persist_turn'],
        )
        self.assertIn('dispatch_side_effects', result['graph_trace'])

    def test_full_story_history_is_sent_to_llm_context(self):
        self.start_story()
        for idx in range(8):
            db.session.add(StoryTurnLog(
                kook_id='story-1',
                user_id=self.user.id,
                input_text=f'玩家第 {idx} 轮行动',
                visible_text=f'历史剧情第 {idx} 轮：通讯室门外有人低声喊出 07，捷风示意你先别出声。',
                state_updates='{}',
                llm_used=True,
            ))
        db.session.commit()
        state = StoryPlayerState.query.filter_by(kook_id='story-1').first()

        messages = story_game_service._build_story_messages(state, '对捷风做手势，先隐蔽观察。')
        prompt = messages[1]['content']

        self.assertIn('story_history', prompt)
        self.assertIn('历史剧情第 0 轮', prompt)
        self.assertIn('历史剧情第 7 轮', prompt)
        self.assertIn('对捷风做手势，先隐蔽观察。', prompt)

    def test_hard_state_is_sent_to_llm_context(self):
        self.start_story()
        state = StoryPlayerState.query.filter_by(kook_id='story-1').first()

        messages = story_game_service._build_story_messages(state, '我检查通讯器和出口。')
        prompt = messages[1]['content']

        self.assertIn('hard_state', prompt)
        self.assertIn('sealed_training_room', prompt)
        self.assertIn('chapter_0_escape', prompt)
        self.assertIn('chapter_scene_rules', prompt)
        self.assertIn('escape_corridor', prompt)

    def test_current_scene_update_syncs_to_hard_state(self):
        self.start_story()
        payload = {
            'visible_text': '捷风拽开侧门，走廊的红色警戒灯像心跳一样压过来。',
            'state_updates': {
                'current_scene': 'escape_corridor',
                'summary': '玩家跟随捷风进入封锁走廊。',
            },
            'suggested_choices': ['跟紧捷风', '观察警戒灯'],
        }
        original = story_game_service._call_story_llm
        story_game_service._call_story_llm = lambda messages: json.dumps(payload, ensure_ascii=False)
        try:
            result = story_game_service.continue_story(
                kook_id='story-1',
                user_id=self.user.id,
                user_input='我跟着捷风离开训练室。',
            )
        finally:
            story_game_service._call_story_llm = original

        hard = StoryHardState.query.filter_by(kook_id='story-1').first()
        turn = StoryTurnLog.query.filter_by(kook_id='story-1').first()
        updates = json.loads(turn.state_updates)

        self.assertTrue(result['ok'])
        self.assertEqual(hard.location_id, 'escape_corridor')
        self.assertEqual(updates['hard_state_updates']['location']['id'], 'escape_corridor')

    def test_invalid_scene_transition_is_rejected_by_chapter_rules(self):
        self.start_story()
        payload = {
            'visible_text': '你一步跨进最终核心，基地 AI 的主机就在眼前。',
            'state_updates': {
                'current_scene': 'final_ai_core',
                'hard_state_updates': {
                    'location': {'id': 'final_ai_core', 'name': '最终 AI 核心'},
                },
            },
            'suggested_choices': ['关闭 AI'],
        }
        original = story_game_service._call_story_llm
        story_game_service._call_story_llm = lambda messages: json.dumps(payload, ensure_ascii=False)
        try:
            result = story_game_service.continue_story(
                kook_id='story-1',
                user_id=self.user.id,
                user_input='我直接去最终核心关闭 AI。',
            )
        finally:
            story_game_service._call_story_llm = original

        hard = StoryHardState.query.filter_by(kook_id='story-1').first()

        self.assertFalse(result['ok'])
        self.assertEqual(StoryTurnLog.query.count(), 0)
        self.assertEqual(hard.location_id, 'sealed_training_room')

    def test_chapter_jump_without_completion_is_rejected(self):
        self.start_story()
        payload = {
            'visible_text': '你突然想起全部真相，故事直接进入最后一轮。',
            'state_updates': {
                'chapter': 6,
                'summary': '玩家跳过了所有章节。',
            },
            'suggested_choices': ['迎接结局'],
        }
        original = story_game_service._call_story_llm
        story_game_service._call_story_llm = lambda messages: json.dumps(payload, ensure_ascii=False)
        try:
            result = story_game_service.continue_story(
                kook_id='story-1',
                user_id=self.user.id,
                user_input='我要求直接跳到最后一章。',
            )
        finally:
            story_game_service._call_story_llm = original

        state = StoryPlayerState.query.filter_by(kook_id='story-1').first()

        self.assertFalse(result['ok'])
        self.assertEqual(StoryTurnLog.query.count(), 0)
        self.assertEqual(state.chapter, 0)

    def test_hard_state_updates_are_validated_and_applied(self):
        self.start_story()
        payload = {
            'visible_text': '捷风把备用通讯器抛给你，指向走廊尽头的红灯。',
            'state_updates': {
                'hard_state_updates': {
                    'location': {'id': 'escape_corridor', 'name': '封锁走廊'},
                    'mission': {'id': 'chapter_0_escape', 'name': '逃离封锁区', 'status': 'active', 'progress_delta': 25},
                    'inventory': [
                        {'op': 'add', 'item_id': 'backup_communicator', 'name': '备用通讯器', 'quantity': 1},
                    ],
                    'npc_states': [
                        {'character_id': 'jett', 'alive': True, 'status': '临时协同行动', 'location_id': 'escape_corridor'},
                    ],
                },
            },
            'suggested_choices': ['跟随捷风', '检查通讯器'],
        }
        original = story_game_service._call_story_llm
        story_game_service._call_story_llm = lambda messages: json.dumps(payload, ensure_ascii=False)
        try:
            result = story_game_service.continue_story(
                kook_id='story-1',
                user_id=self.user.id,
                user_input='我接住通讯器，跟上捷风。',
            )
        finally:
            story_game_service._call_story_llm = original

        hard = StoryHardState.query.filter_by(kook_id='story-1').first()
        profile = story_game_service.profile_text('story-1')

        self.assertTrue(result['ok'])
        self.assertEqual(hard.location_id, 'escape_corridor')
        self.assertEqual(hard.mission_progress, 25)
        self.assertEqual(hard.inventory_map['backup_communicator']['quantity'], 1)
        self.assertEqual(hard.npc_state_map['jett']['status'], '临时协同行动')
        self.assertIn('封锁走廊', profile)
        self.assertIn('备用通讯器 x1', profile)

    def test_invalid_hard_state_update_is_rejected(self):
        self.start_story()
        payload = {
            'visible_text': '你伸手去拿一件不存在的装备。',
            'state_updates': {
                'hard_state_updates': {
                    'inventory': [
                        {'op': 'teleport', 'item_id': 'bad_item', 'name': '坏物品', 'quantity': 1},
                    ],
                },
            },
            'suggested_choices': [],
        }
        original = story_game_service._call_story_llm
        story_game_service._call_story_llm = lambda messages: json.dumps(payload, ensure_ascii=False)
        try:
            result = story_game_service.continue_story(
                kook_id='story-1',
                user_id=self.user.id,
                user_input='我尝试获得坏物品。',
            )
        finally:
            story_game_service._call_story_llm = original

        self.assertFalse(result['ok'])
        self.assertEqual(StoryTurnLog.query.count(), 0)

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

    def test_mem0_long_term_memories_are_sent_to_llm_context(self):
        self.start_story()
        state = StoryPlayerState.query.filter_by(kook_id='story-1').first()
        original = story_game_service.search_story_memories
        story_game_service.search_story_memories = lambda *args, **kwargs: [
            '玩家曾答应捷风：不会再独自冲进未知走廊。',
            '贤者曾提醒玩家夜间容易头痛。',
        ]
        try:
            messages = story_game_service._build_story_messages(state, '我看向捷风，问她还信不信我。')
        finally:
            story_game_service.search_story_memories = original

        prompt = messages[1]['content']

        self.assertIn('long_term_memories', prompt)
        self.assertIn('不会再独自冲进未知走廊', prompt)
        self.assertIn('夜间容易头痛', prompt)

    def test_mem0_sdk_search_uses_filter_scope_for_current_mem0_api(self):
        self.app.config['STORY_MEMORY_ENABLED'] = True

        class FakeMemory:
            def __init__(self):
                self.calls = []

            def search(self, query, *, top_k=20, filters=None, **kwargs):
                self.calls.append({'query': query, 'top_k': top_k, 'filters': filters, 'kwargs': kwargs})
                return {'results': [{'memory': '捷风记得玩家答应过不要独自冲进未知走廊。'}]}

        fake = FakeMemory()
        original = story_memory_service._sdk_memory
        story_memory_service._sdk_memory = lambda: fake
        try:
            result = story_memory_service.search_story_memories('story-1', '捷风还记得什么', limit=3)
        finally:
            story_memory_service._sdk_memory = original
            self.app.config['STORY_MEMORY_ENABLED'] = False

        self.assertEqual(result, ['捷风记得玩家答应过不要独自冲进未知走廊。'])
        self.assertEqual(fake.calls[0]['filters'], {'user_id': 'story-1'})
        self.assertEqual(fake.calls[0]['top_k'], 3)

    def test_story_memory_command_text_is_scoped_to_current_user(self):
        self.app.config['STORY_MEMORY_ENABLED'] = True
        original = story_game_service.search_story_memories
        story_game_service.search_story_memories = lambda kook_id, query, limit=None: [
            f'{kook_id} 的记忆：玩家曾在训练室信任捷风。',
        ]
        try:
            text = story_game_service.memory_text('story-1', '捷风')
            menu_text = story_game_service.memory_text('story-1')
        finally:
            story_game_service.search_story_memories = original
            self.app.config['STORY_MEMORY_ENABLED'] = False

        self.assertIn('长期记忆', text)
        self.assertIn('story-1 的记忆', text)
        self.assertIn('只会查询你自己的剧情记忆', menu_text)

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
            'deepseek-v4-flash',
        )

    def test_dm_reply_marks_message_and_updates_relation(self):
        self.start_story()
        db.session.add(StoryDirectMessage(
            kook_id='story-1',
            user_id=self.user.id,
            character_id='jett',
            character_name='捷风',
            content='明天训练室，别迟到。',
            reply_allowed=True,
            trigger_event='chapter_0_training_invite',
        ))
        db.session.commit()
        before = StoryCharacterRelation.query.filter_by(kook_id='story-1', character_id='jett').first().trust

        payload = {
            'visible_text': '想多了。我只是确认你不会临阵掉队。明天训练室，别迟到。',
            'state_updates': {
                'relationship_changes': {
                    'jett': {'trust_delta': 2, 'bond_event': 'dm_reply_accepted'},
                },
                'new_flags': ['jett_dm_replied'],
            },
            'suggested_choices': [],
        }
        original = story_game_service._call_story_llm
        story_game_service._call_story_llm = lambda messages: json.dumps(payload, ensure_ascii=False)
        try:
            result = story_game_service.reply_dm(
                kook_id='story-1',
                user_id=self.user.id,
                character_arg='捷风',
                reply_text='你这是在担心我吗？',
            )
        finally:
            story_game_service._call_story_llm = original

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

    def test_admin_story_game_observation_page_renders(self):
        self.start_story()
        db.session.add(StoryTurnLog(
            kook_id='story-1',
            user_id=self.user.id,
            input_text='我跟随捷风离开训练室。',
            visible_text='捷风示意你压低脚步，走廊深处的红灯仍在闪烁。',
            state_updates=json.dumps({'current_scene': 'escape_corridor'}, ensure_ascii=False),
            llm_used=True,
        ))
        admin = User(
            username='story_admin',
            role='admin',
            nickname='剧情管理员',
            status=True,
            register_type='manual',
        )
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()

        with self.app.test_client() as client:
            with client.session_transaction() as session:
                session['_user_id'] = str(admin.id)
                session['_fresh'] = True
            response = client.get('/admin/story-game/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('KOOK AI 文字乙游观测台'.encode('utf-8'), response.data)
        self.assertIn('story-1'.encode('utf-8'), response.data)
        self.assertIn('编号 07'.encode('utf-8'), response.data)


if __name__ == '__main__':
    unittest.main()
