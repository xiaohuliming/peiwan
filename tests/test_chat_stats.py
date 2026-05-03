import os
import tempfile
import unittest
from datetime import datetime, timedelta

from flask import g

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.chat_stats import ChatBotProfile, ChatDailyUserStat, ChatRankSettlement
from app.models.user import User
from app.services import chat_stats_service


class ChatStatsTestConfig(Config):
    TESTING = True
    SECRET_KEY = 'test-secret'
    KOOK_BOT_ENABLED = False
    PUBLIC_SITE_URL = 'http://localhost'
    SITE_URL = 'http://localhost'


class ChatStatsTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.db_path = path

        ChatStatsTestConfig.SQLALCHEMY_DATABASE_URI = f'sqlite:///{self.db_path}'
        self.app = create_app(ChatStatsTestConfig, start_background_tasks=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()
        self._seq = 0

        cfg = chat_stats_service.get_config(create=True)
        cfg.channel_id_list = ['chan-1']
        cfg.whitelist_kook_id_list = ['white-1']
        cfg.duplicate_limit = 2
        cfg.rank_limit = 10
        cfg.rank_broadcast_enabled = False
        cfg.checkin_broadcast_enabled = False
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def make_user(self, role='god', kook_id=None, username=None):
        self._seq += 1
        user = User(
            username=username or f'user_{self._seq}',
            role=role,
            nickname=f'Nick {self._seq}',
            kook_id=kook_id,
            kook_username=f'kook#{self._seq}',
            kook_bound=bool(kook_id),
            status=True,
            register_type='manual',
        )
        user.set_password('password')
        db.session.add(user)
        db.session.flush()
        return user

    def login(self, user):
        g.pop('_login_user', None)
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def test_whitelist_and_channel_filter(self):
        staff = self.make_user(role='staff', kook_id='staff-1')
        db.session.commit()

        ignored_channel = chat_stats_service.record_message('other-chan', 'user-1', 'User#1', 'hello')
        ignored_manual = chat_stats_service.record_message('chan-1', 'white-1', 'White#1', 'hello')
        ignored_staff = chat_stats_service.record_message('chan-1', 'staff-1', 'Staff#1', 'hello', user_id=staff.id)

        self.assertEqual(ignored_channel['reason'], 'channel')
        self.assertEqual(ignored_manual['reason'], 'whitelist')
        self.assertEqual(ignored_staff['reason'], 'whitelist')
        self.assertEqual(ChatDailyUserStat.query.count(), 0)

    def test_duplicate_and_meaningless_filter(self):
        user = self.make_user(role='god', kook_id='user-1')
        db.session.commit()

        chat_stats_service.record_message('chan-1', 'user-1', 'User#1', 'hello', user_id=user.id)
        chat_stats_service.record_message('chan-1', 'user-1', 'User#1', 'hello', user_id=user.id)
        duplicate = chat_stats_service.record_message('chan-1', 'user-1', 'User#1', 'hello', user_id=user.id)
        meaningless = chat_stats_service.record_message('chan-1', 'user-1', 'User#1', '1111', user_id=user.id)

        stat = ChatDailyUserStat.query.filter_by(kook_id='user-1').first()
        self.assertEqual(duplicate['reason'], 'duplicate')
        self.assertEqual(meaningless['reason'], 'meaningless')
        self.assertEqual(stat.total_count, 4)
        self.assertEqual(stat.valid_count, 2)
        self.assertEqual(stat.duplicate_filtered_count, 1)
        self.assertEqual(stat.meaningless_filtered_count, 1)

    def test_daily_settlement_is_top_ten_and_idempotent(self):
        base = datetime(2026, 5, 2, 12, 0, 0)
        for idx in range(12):
            kook_id = f'user-{idx}'
            user = self.make_user(role='god', kook_id=kook_id)
            db.session.commit()
            for n in range(idx + 1):
                chat_stats_service.record_message(
                    'chan-1',
                    kook_id,
                    f'User#{idx}',
                    f'unique message {idx}-{n}',
                    user_id=user.id,
                    occurred_at=base,
                )

        count, rows = chat_stats_service.settle_daily(base.date())
        again_count, again_rows = chat_stats_service.settle_daily(base.date())

        self.assertEqual(count, 10)
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0].kook_id, 'user-11')
        self.assertEqual(rows[0].valid_count, 12)
        self.assertEqual(again_count, 0)
        self.assertEqual(len(again_rows), 10)
        self.assertEqual(ChatRankSettlement.query.count(), 10)

    def test_checkin_streak_and_milestone_reward(self):
        user = self.make_user(role='god', kook_id='check-1')
        db.session.commit()
        start = datetime(2026, 5, 1, 10, 0, 0)

        last = None
        for offset in range(10):
            last = chat_stats_service.perform_checkin(
                'chan-1',
                'check-1',
                'Check#1',
                user_id=user.id,
                occurred_at=start + timedelta(days=offset),
            )

        duplicate = chat_stats_service.perform_checkin(
            'chan-1',
            'check-1',
            'Check#1',
            user_id=user.id,
            occurred_at=start + timedelta(days=9),
        )
        profile = ChatBotProfile.query.filter_by(kook_id='check-1').first()

        self.assertTrue(last['ok'])
        self.assertEqual(last['reward_title'], '十日连签')
        self.assertFalse(duplicate['ok'])
        self.assertEqual(profile.sign_in_streak, 10)
        self.assertEqual(profile.total_checkins, 10)
        self.assertEqual(profile.title, '十日连签')

    def test_admin_page_requires_admin(self):
        staff = self.make_user(role='staff', username='staff')
        admin = self.make_user(role='admin', username='admin')
        db.session.commit()

        self.login(staff)
        staff_resp = self.client.get('/admin/chat-stats/')
        self.assertEqual(staff_resp.status_code, 302)

        self.login(admin)
        admin_resp = self.client.get('/admin/chat-stats/')
        self.assertEqual(admin_resp.status_code, 200)
        self.assertIn('KOOK 发言统计机器人'.encode('utf-8'), admin_resp.data)


if __name__ == '__main__':
    unittest.main()
