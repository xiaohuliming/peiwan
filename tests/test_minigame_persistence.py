import os
import tempfile
import time
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.minigame import MiniGameRecord
from app.models.user import User
from app.services import minigame_service


class MiniGameTestConfig(Config):
    TESTING = True
    SECRET_KEY = 'test-secret'
    KOOK_BOT_ENABLED = False
    PUBLIC_SITE_URL = 'http://localhost'
    SITE_URL = 'http://localhost'


class MiniGamePersistenceTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.db_path = path

        MiniGameTestConfig.SQLALCHEMY_DATABASE_URI = f'sqlite:///{self.db_path}'
        self.app = create_app(MiniGameTestConfig, start_background_tasks=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        winner = User(username='winner', role='god', nickname='赢家', kook_id='user-1', kook_bound=True)
        winner.set_password('password')
        loser = User(username='loser', role='god', nickname='输家', kook_id='user-2', kook_bound=True)
        loser.set_password('password')
        db.session.add_all([winner, loser])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_records_connect4_result_and_builds_leaderboard(self):
        now = time.time()
        record = minigame_service.record_minigame_result({
            'game': 'connect4',
            'channel_id': 'chan-1',
            'players': [
                {'id': 'user-1', 'name': '赢家'},
                {'id': 'user-2', 'name': '输家'},
            ],
            'winner_id': 'user-1',
            'winner_name': '赢家',
            'result': 'win',
            'end_reason': 'connect4',
            'moves': 7,
            'started_at': now - 60,
            'ended_at': now,
        })

        self.assertIsNotNone(record.id)
        self.assertEqual(MiniGameRecord.query.count(), 1)

        ranking = minigame_service.get_leaderboard('四子棋')
        self.assertEqual(ranking[0]['kook_id'], 'user-1')
        self.assertEqual(ranking[0]['wins'], 1)
        self.assertEqual(ranking[1]['kook_id'], 'user-2')
        self.assertEqual(ranking[1]['losses'], 1)

        message = minigame_service.format_leaderboard('四子棋')
        self.assertIn('小游戏排行榜 · 四子棋', message)
        self.assertIn('1胜', message)


if __name__ == '__main__':
    unittest.main()
