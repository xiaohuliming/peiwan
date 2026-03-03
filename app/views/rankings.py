from datetime import datetime, timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import func, desc

from app.extensions import db
from app.models.order import Order
from app.models.gift import GiftOrder
from app.models.intimacy import Intimacy
from app.models.user import User

rankings_bp = Blueprint('rankings', __name__, template_folder='../templates')


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
        # 陪玩接单排行: 按到手小猪粮排序 (订单+礼物)
        # 订单收益
        order_earnings = db.session.query(
            Order.player_id,
            func.sum(Order.player_earning).label('order_earning')
        ).filter(
            Order.status == 'paid',
            Order.pay_time >= start_date,
            Order.pay_time < end_date
        ).group_by(Order.player_id).subquery()

        # 礼物收益
        gift_earnings = db.session.query(
            GiftOrder.player_id,
            func.sum(GiftOrder.player_earning).label('gift_earning')
        ).filter(
            GiftOrder.status == 'paid',
            GiftOrder.created_at >= start_date,
            GiftOrder.created_at < end_date
        ).group_by(GiftOrder.player_id).subquery()

        # 合并
        results = db.session.query(
            User,
            func.coalesce(order_earnings.c.order_earning, 0).label('order_earning'),
            func.coalesce(gift_earnings.c.gift_earning, 0).label('gift_earning'),
        ).outerjoin(
            order_earnings, User.id == order_earnings.c.player_id
        ).outerjoin(
            gift_earnings, User.id == gift_earnings.c.player_id
        ).filter(
            User.role == 'player',
            db.or_(order_earnings.c.order_earning != None, gift_earnings.c.gift_earning != None)
        ).all()

        for user, oe, ge in results:
            total = Decimal(str(oe or 0)) + Decimal(str(ge or 0))
            player_ranking.append({
                'user': user,
                'order_earning': Decimal(str(oe or 0)),
                'gift_earning': Decimal(str(ge or 0)),
                'total': total,
            })
        player_ranking.sort(key=lambda x: x['total'], reverse=True)

    elif tab == 'boss':
        # 老板消费排行: 按消费嗯呢币排序 (订单+礼物)
        order_spend = db.session.query(
            Order.boss_id,
            func.sum(Order.total_price).label('order_spend')
        ).filter(
            Order.status.in_(['paid', 'pending_pay']),
            Order.created_at >= start_date,
            Order.created_at < end_date
        ).group_by(Order.boss_id).subquery()

        gift_spend = db.session.query(
            GiftOrder.boss_id,
            func.sum(GiftOrder.total_price).label('gift_spend')
        ).filter(
            GiftOrder.status == 'paid',
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
            boss_ranking.append({
                'user': user,
                'order_spend': Decimal(str(os_val or 0)),
                'gift_spend': Decimal(str(gs_val or 0)),
                'total': total,
            })
        boss_ranking.sort(key=lambda x: x['total'], reverse=True)

    elif tab == 'intimacy':
        # 亲密度排行
        intimacy_ranking = Intimacy.query.filter(
            Intimacy.value > 0
        ).order_by(
            desc(Intimacy.value)
        ).limit(100).all()

    return render_template('rankings/index.html',
                           tab=tab,
                           period=period,
                           player_ranking=player_ranking,
                           boss_ranking=boss_ranking,
                           intimacy_ranking=intimacy_ranking)
