import os
import tempfile
import unittest
from decimal import Decimal

from app import create_app
from app.config import Config
from app.extensions import db
from app.models.finance import WithdrawRequest
from app.models.gift import Gift, GiftOrder
from app.models.order import Order
from app.models.user import User
from app.services.frozen_balance_service import (
    build_frozen_reconciliation_rows,
    get_user_frozen_breakdown,
    reconcile_frozen_balance_cache,
)
from app.services.order_service import refund_order


class FrozenBalanceTestConfig(Config):
    TESTING = True
    SECRET_KEY = 'test-secret'
    KOOK_BOT_ENABLED = False
    PUBLIC_SITE_URL = 'http://localhost'
    SITE_URL = 'http://localhost'


class FrozenBalanceTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.db_path = path

        FrozenBalanceTestConfig.SQLALCHEMY_DATABASE_URI = f'sqlite:///{self.db_path}'
        self.app = create_app(FrozenBalanceTestConfig, start_background_tasks=False)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        self.client = self.app.test_client()
        self._seq = 0

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def make_user(
        self,
        role='player',
        username=None,
        nickname=None,
        player_nickname=None,
        m_coin='0.00',
        m_coin_gift='0.00',
        m_bean='0.00',
        m_bean_frozen='0.00',
    ):
        self._seq += 1
        user = User(
            username=username or f'user_{self._seq}',
            role=role,
            nickname=nickname or f'Nick {self._seq}',
            player_nickname=player_nickname if player_nickname is not None else (f'Player {self._seq}' if role == 'player' else None),
            status=True,
            register_type='manual',
            m_coin=Decimal(str(m_coin)),
            m_coin_gift=Decimal(str(m_coin_gift)),
            m_bean=Decimal(str(m_bean)),
            m_bean_frozen=Decimal(str(m_bean_frozen)),
        )
        user.set_password('password')
        db.session.add(user)
        db.session.flush()
        return user

    def make_withdraw(self, user, amount, status='pending'):
        wr = WithdrawRequest(
            user_id=user.id,
            amount=Decimal(str(amount)),
            payment_method='wechat',
            payment_account='wx',
            status=status,
        )
        db.session.add(wr)
        db.session.flush()
        return wr

    def make_gift(self, gift_type='crown', price='10.00', name=None):
        self._seq += 1
        gift = Gift(
            name=name or f'Gift {self._seq}',
            price=Decimal(str(price)),
            gift_type=gift_type,
            status=True,
        )
        db.session.add(gift)
        db.session.flush()
        return gift

    def make_order(self, boss, player, player_earning, status='paid', freeze_status='frozen', total_price=None):
        self._seq += 1
        total_price = Decimal(str(total_price if total_price is not None else player_earning))
        order = Order(
            order_no=f'ORD{self._seq:06d}',
            boss_id=boss.id,
            player_id=player.id,
            total_price=total_price,
            player_earning=Decimal(str(player_earning)),
            shop_earning=Decimal('0.00'),
            order_type='escort',
            status=status,
            freeze_status=freeze_status,
            boss_hold_coin=total_price,
            boss_hold_gift=Decimal('0.00'),
        )
        db.session.add(order)
        db.session.flush()
        return order

    def make_gift_order(self, boss, player, gift, player_earning, status='paid', freeze_status='frozen', total_price=None):
        total_price = Decimal(str(total_price if total_price is not None else player_earning))
        gift_order = GiftOrder(
            boss_id=boss.id,
            player_id=player.id,
            gift_id=gift.id,
            quantity=1,
            unit_price=total_price,
            total_price=total_price,
            commission_rate=Decimal('80.00'),
            player_earning=Decimal(str(player_earning)),
            shop_earning=Decimal('0.00'),
            boss_paid_coin=total_price,
            boss_paid_gift=Decimal('0.00'),
            status=status,
            freeze_status=freeze_status,
        )
        db.session.add(gift_order)
        db.session.flush()
        return gift_order

    def login(self, user):
        with self.client.session_transaction() as session:
            session['_user_id'] = str(user.id)
            session['_fresh'] = True

    def test_breakdown_withdraw_only(self):
        player = self.make_user(m_bean_frozen='120.50')
        self.make_withdraw(player, '120.50', status='pending')
        db.session.commit()

        breakdown = get_user_frozen_breakdown(player)

        self.assertEqual(breakdown['pending_withdraw'], Decimal('120.50'))
        self.assertEqual(breakdown['order'], Decimal('0.00'))
        self.assertEqual(breakdown['gift'], Decimal('0.00'))
        self.assertEqual(breakdown['total'], Decimal('120.50'))
        self.assertEqual(breakdown['legacy_diff'], Decimal('0.00'))

    def test_breakdown_order_only(self):
        boss = self.make_user(role='god', m_coin='500.00')
        player = self.make_user(m_bean_frozen='88.00')
        self.make_order(boss, player, '88.00', status='paid', freeze_status='frozen')
        db.session.commit()

        breakdown = get_user_frozen_breakdown(player)

        self.assertEqual(breakdown['pending_withdraw'], Decimal('0.00'))
        self.assertEqual(breakdown['order'], Decimal('88.00'))
        self.assertEqual(breakdown['gift'], Decimal('0.00'))
        self.assertEqual(breakdown['total'], Decimal('88.00'))

    def test_breakdown_gift_only(self):
        boss = self.make_user(role='god', m_coin='500.00')
        player = self.make_user(m_bean_frozen='66.00')
        gift = self.make_gift(gift_type='crown', price='82.50')
        self.make_gift_order(boss, player, gift, '66.00', status='paid', freeze_status='frozen', total_price='82.50')
        db.session.commit()

        breakdown = get_user_frozen_breakdown(player)

        self.assertEqual(breakdown['pending_withdraw'], Decimal('0.00'))
        self.assertEqual(breakdown['order'], Decimal('0.00'))
        self.assertEqual(breakdown['gift'], Decimal('66.00'))
        self.assertEqual(breakdown['total'], Decimal('66.00'))

    def test_breakdown_mixed_sources(self):
        boss = self.make_user(role='god', m_coin='1000.00')
        player = self.make_user(m_bean_frozen='210.00')
        gift = self.make_gift(gift_type='crown', price='100.00')
        self.make_withdraw(player, '60.00', status='pending')
        self.make_order(boss, player, '70.00', status='paid', freeze_status='frozen')
        self.make_gift_order(boss, player, gift, '80.00', status='paid', freeze_status='frozen', total_price='100.00')
        db.session.commit()

        breakdown = get_user_frozen_breakdown(player)

        self.assertEqual(breakdown['pending_withdraw'], Decimal('60.00'))
        self.assertEqual(breakdown['order'], Decimal('70.00'))
        self.assertEqual(breakdown['gift'], Decimal('80.00'))
        self.assertEqual(breakdown['earning_frozen'], Decimal('150.00'))
        self.assertEqual(breakdown['total'], Decimal('210.00'))
        self.assertEqual(breakdown['legacy_diff'], Decimal('0.00'))

    def test_wallet_page_uses_realtime_total_when_legacy_cache_is_dirty(self):
        boss = self.make_user(role='god', m_coin='5000.00')
        player = self.make_user(
            m_bean='1867.94',
            m_bean_frozen='1342.40',
            player_nickname='beat#4599',
        )
        gift = self.make_gift(gift_type='crown', price='2628.00', name='Crown Gift')
        self.make_gift_order(boss, player, gift, '2102.40', status='paid', freeze_status='frozen', total_price='2628.00')
        db.session.commit()

        self.login(player)
        response = self.client.get('/finance/wallet')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('冻结中: 2102.40 豆', html)
        self.assertIn('-760.00', html)
        self.assertNotIn('冻结中: 1342.40 豆', html)

    def test_user_detail_page_uses_realtime_total_when_legacy_cache_is_dirty(self):
        boss = self.make_user(role='god', m_coin='5000.00')
        admin = self.make_user(role='admin', username='admin_user', nickname='Admin')
        player = self.make_user(
            m_bean='1867.94',
            m_bean_frozen='1342.40',
            player_nickname='beat#4599',
        )
        gift = self.make_gift(gift_type='crown', price='2628.00', name='Crown Gift')
        self.make_gift_order(boss, player, gift, '2102.40', status='paid', freeze_status='frozen', total_price='2628.00')
        db.session.commit()

        self.login(admin)
        response = self.client.get(f'/users/{player.id}')
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('冻结: 2102.40', html)
        self.assertIn('-760.00', html)

    def test_refund_order_does_not_treat_pending_withdraw_as_order_or_gift_frozen(self):
        boss = self.make_user(role='god', m_coin='0.00')
        player = self.make_user(m_bean='0.00', m_bean_frozen='80.00')
        self.make_withdraw(player, '80.00', status='pending')
        order = self.make_order(
            boss,
            player,
            '80.00',
            status='paid',
            freeze_status='normal',
            total_price='100.00',
        )
        db.session.commit()

        ok, message = refund_order(order)

        self.assertFalse(ok)
        self.assertIn('差额 80.00', message)
        self.assertEqual(order.status, 'paid')

    def test_reconcile_script_helper_can_fix_dirty_legacy_cache(self):
        boss = self.make_user(role='god', m_coin='5000.00')
        player = self.make_user(
            m_bean='1867.94',
            m_bean_frozen='1342.40',
            player_nickname='beat#4599',
        )
        gift = self.make_gift(gift_type='crown', price='2628.00', name='Crown Gift')
        self.make_gift_order(boss, player, gift, '2102.40', status='paid', freeze_status='frozen', total_price='2628.00')
        db.session.commit()

        rows = build_frozen_reconciliation_rows(user_id=player.id)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['legacy_cache'], Decimal('1342.40'))
        self.assertEqual(rows[0]['realtime_total'], Decimal('2102.40'))
        self.assertEqual(rows[0]['legacy_diff'], Decimal('-760.00'))

        updated_rows = reconcile_frozen_balance_cache(rows)
        db.session.commit()
        db.session.refresh(player)

        self.assertEqual(len(updated_rows), 1)
        self.assertEqual(player.m_bean_frozen, Decimal('2102.40'))
        self.assertEqual(get_user_frozen_breakdown(player)['legacy_diff'], Decimal('0.00'))


if __name__ == '__main__':
    unittest.main()
