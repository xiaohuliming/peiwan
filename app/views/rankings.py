from datetime import datetime, timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import func, desc
from sqlalchemy.orm import aliased

from app.extensions import db
from app.models.order import Order
from app.models.gift import GiftOrder
from app.models.intimacy import Intimacy
from app.models.user import User

rankings_bp = Blueprint('rankings', __name__, template_folder='../templates')


ANON_AVATAR_URL = '/static/img/anonymous-avatar.svg'


def _is_user_anonymous_for_ranking(user):
    if not user:
        return False
    return any([
        bool(getattr(user, 'anonymous_recharge', False)),
        bool(getattr(user, 'anonymous_consume', False)),
        bool(getattr(user, 'anonymous_gift_send', False)),
        bool(getattr(user, 'anonymous_gift_recv', False)),
        bool(getattr(user, 'anonymous_upgrade', False)),
    ])


def _build_ranking_profile(user, prefer_player_name=False, anonymous_label='匿名用户'):
    if prefer_player_name:
        real_name = user.player_nickname or user.nickname or user.username
    else:
        real_name = user.nickname or user.username

    anonymous = _is_user_anonymous_for_ranking(user)
    if anonymous:
        return {
            'name': anonymous_label,
            'avatar': ANON_AVATAR_URL,
            'code': '******',
            'anonymous': True,
            'real_name': real_name,
            'real_avatar': user.avatar_url,
            'real_code': user.user_code,
        }

    return {
        'name': real_name,
        'avatar': user.avatar_url,
        'code': user.user_code,
        'anonymous': False,
        'real_name': real_name,
        'real_avatar': user.avatar_url,
        'real_code': user.user_code,
    }


def _parse_date_range(period):
    """根据时间筛选返回 (start_date, end_date)"""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if period == 'today':
        return today, today + timedelta(days=1)
    elif period == 'yesterday':
        return today - timedelta(days=1), today
    elif period == 'this_week':
        start = today - timedelta(days=today.weekday())
        return start, today + timedelta(days=1)
    elif period == 'last_week':
        start = today - timedelta(days=today.weekday() + 7)
        end = start + timedelta(days=7)
        return start, end
    elif period == 'this_month':
        start = today.replace(day=1)
        return start, today + timedelta(days=1)
    elif period == 'last_month':
        first_of_month = today.replace(day=1)
        end = first_of_month
        start = (first_of_month - timedelta(days=1)).replace(day=1)
        return start, end
    elif period == 'this_quarter':
        q = (today.month - 1) // 3
        start = today.replace(month=q * 3 + 1, day=1)
        return start, today + timedelta(days=1)
    elif period == 'this_year':
        start = today.replace(month=1, day=1)
        return start, today + timedelta(days=1)
    elif period == 'last_7':
        return today - timedelta(days=7), today + timedelta(days=1)
    elif period == 'last_30':
        return today - timedelta(days=30), today + timedelta(days=1)
    else:
        # 默认本月
        start = today.replace(day=1)
        return start, today + timedelta(days=1)


@rankings_bp.route('/')
@login_required
def index():
    period = request.args.get('period', 'this_month')
    tab = request.args.get('tab', 'player')
    start_date, end_date = _parse_date_range(period)

    player_ranking = []
    boss_ranking = []
    intimacy_ranking = []

    if tab == 'player':
        # 陪玩收益排行：仅统计“已结算且已解冻”的订单/礼物收益（不计冻结，不计退款）
        order_income = db.session.query(
            Order.player_id.label('player_id'),
            func.sum(Order.player_earning).label('order_earning'),
        ).filter(
            Order.status == 'paid',
            Order.freeze_status == 'normal',
            Order.created_at >= start_date,
            Order.created_at < end_date,
        ).group_by(Order.player_id).subquery()

        gift_income = db.session.query(
            GiftOrder.player_id.label('player_id'),
            func.sum(GiftOrder.player_earning).label('gift_earning'),
        ).filter(
            GiftOrder.status == 'paid',
            GiftOrder.freeze_status == 'normal',
            GiftOrder.created_at >= start_date,
            GiftOrder.created_at < end_date,
        ).group_by(GiftOrder.player_id).subquery()

        results = db.session.query(
            User,
            func.coalesce(order_income.c.order_earning, 0).label('order_earning'),
            func.coalesce(gift_income.c.gift_earning, 0).label('gift_earning'),
        ).outerjoin(
            order_income, User.id == order_income.c.player_id
        ).outerjoin(
            gift_income, User.id == gift_income.c.player_id
        ).filter(
            User.role_filter_expr('player'),
            db.or_(
                order_income.c.order_earning != None,
                gift_income.c.gift_earning != None,
            )
        ).all()

        for user, oe, ge in results:
            total = Decimal(str(oe or 0)) + Decimal(str(ge or 0))
            profile = _build_ranking_profile(user, prefer_player_name=True, anonymous_label='匿名陪玩')
            player_ranking.append({
                'user': user,
                'order_earning': Decimal(str(oe or 0)),
                'gift_earning': Decimal(str(ge or 0)),
                'total': total,
                'display_name': profile['name'],
                'display_avatar': profile['avatar'],
                'display_code': profile['code'],
                'is_anonymous': profile['anonymous'],
                'real_name': profile['real_name'],
                'real_avatar': profile['real_avatar'],
                'real_code': profile['real_code'],
            })
        player_ranking.sort(key=lambda x: x['total'], reverse=True)

    elif tab == 'boss':
        # 老板消费排行：仅统计“已结算且已解冻”的订单/礼物（不计冻结，不计退款）
        order_spend = db.session.query(
            Order.boss_id,
            func.sum(Order.total_price).label('order_spend')
        ).filter(
            Order.status == 'paid',
            Order.freeze_status == 'normal',
            Order.created_at >= start_date,
            Order.created_at < end_date
        ).group_by(Order.boss_id).subquery()

        gift_spend = db.session.query(
            GiftOrder.boss_id,
            func.sum(GiftOrder.total_price).label('gift_spend')
        ).filter(
            GiftOrder.status == 'paid',
            GiftOrder.freeze_status == 'normal',
            GiftOrder.created_at >= start_date,
            GiftOrder.created_at < end_date
        ).group_by(GiftOrder.boss_id).subquery()

        results = db.session.query(
            User,
            func.coalesce(order_spend.c.order_spend, 0).label('order_spend'),
            func.coalesce(gift_spend.c.gift_spend, 0).label('gift_spend'),
        ).outerjoin(
            order_spend, User.id == order_spend.c.boss_id
        ).outerjoin(
            gift_spend, User.id == gift_spend.c.boss_id
        ).filter(
            User.role == 'god',
            db.or_(order_spend.c.order_spend != None, gift_spend.c.gift_spend != None)
        ).all()

        for user, os_val, gs_val in results:
            total = Decimal(str(os_val or 0)) + Decimal(str(gs_val or 0))
            profile = _build_ranking_profile(user, prefer_player_name=False, anonymous_label='匿名老板')
            boss_ranking.append({
                'user': user,
                'order_spend': Decimal(str(os_val or 0)),
                'gift_spend': Decimal(str(gs_val or 0)),
                'total': total,
                'display_name': profile['name'],
                'display_avatar': profile['avatar'],
                'display_code': profile['code'],
                'is_anonymous': profile['anonymous'],
                'real_name': profile['real_name'],
                'real_avatar': profile['real_avatar'],
                'real_code': profile['real_code'],
            })
        boss_ranking.sort(key=lambda x: x['total'], reverse=True)

    elif tab == 'intimacy':
        # 亲密度排行：读取 intimacy 当前值，支持手动修改后即时生效
        BossUser = aliased(User)
        PlayerUser = aliased(User)

        rows = db.session.query(
            Intimacy,
            BossUser,
            PlayerUser,
        ).join(
            BossUser, Intimacy.boss_id == BossUser.id
        ).join(
            PlayerUser, Intimacy.player_id == PlayerUser.id
        ).filter(
            Intimacy.value > 0
        ).order_by(
            desc(Intimacy.value),
            desc(Intimacy.updated_at)
        ).limit(100).all()

        intimacy_ranking = []
        for intimacy, boss, player in rows:
            boss_profile = _build_ranking_profile(boss, prefer_player_name=False, anonymous_label='匿名老板')
            player_profile = _build_ranking_profile(player, prefer_player_name=True, anonymous_label='匿名陪玩')
            intimacy_ranking.append({
                'boss': boss,
                'player': player,
                'value': Decimal(str(intimacy.value or 0)),
                'boss_display_name': boss_profile['name'],
                'boss_display_avatar': boss_profile['avatar'],
                'boss_is_anonymous': boss_profile['anonymous'],
                'boss_real_name': boss_profile['real_name'],
                'boss_real_avatar': boss_profile['real_avatar'],
                'player_display_name': player_profile['name'],
                'player_display_avatar': player_profile['avatar'],
                'player_is_anonymous': player_profile['anonymous'],
                'player_real_name': player_profile['real_name'],
                'player_real_avatar': player_profile['real_avatar'],
            })

    return render_template('rankings/index.html',
                           tab=tab,
                           period=period,
                           player_ranking=player_ranking,
                           boss_ranking=boss_ranking,
                           intimacy_ranking=intimacy_ranking)
