from datetime import datetime, timedelta

from flask import url_for

from app.models.finance import WithdrawRequest
from app.models.gift import GiftOrder
from app.models.lottery import Lottery
from app.models.order import Order
from app.models.vip import UpgradeRecord


def get_top_notifications(user):
    """聚合顶部铃铛消息：返回待办项和总数量。"""
    if not user or not getattr(user, 'is_authenticated', False):
        return {'total': 0, 'items': []}

    items = []

    def add_item(title, count, endpoint, desc='', icon='bell', **params):
        cnt = int(count or 0)
        if cnt <= 0:
            return
        items.append({
            'title': title,
            'count': cnt,
            'url': url_for(endpoint, **params),
            'desc': desc,
            'icon': icon,
        })

    if user.is_staff:
        add_item(
            '待申报订单',
            Order.query.filter(Order.status == 'pending_report').count(),
            'orders.index',
            desc='有订单等待陪玩申报',
            icon='clipboard-list',
            status='pending_report',
        )
        add_item(
            '待确认订单',
            Order.query.filter(Order.status == 'pending_confirm').count(),
            'orders.index',
            desc='等待老板确认支付',
            icon='check-check',
            status='pending_confirm',
        )
        add_item(
            '待结算护航/代练',
            Order.query.filter(
                Order.status == 'pending_pay',
                Order.order_type.in_(('escort', 'training'))
            ).count(),
            'orders.index',
            desc='可由客服手动结算',
            icon='wallet',
            status='pending_pay',
        )
        add_item(
            '礼物冻结待处理',
            GiftOrder.query.filter(
                GiftOrder.status == 'paid',
                GiftOrder.freeze_status == 'frozen'
            ).count(),
            'gifts.index',
            desc='有礼物订单冻结中',
            icon='gift',
        )
        add_item(
            '升级权益待发放',
            UpgradeRecord.query.filter(UpgradeRecord.benefit_status == 'pending').count(),
            'upgrade_admin.index',
            desc='有用户升级权益待确认',
            icon='sparkles',
            status='pending',
        )

        # 即将开奖提醒（10分钟内）
        now = datetime.now()
        due_soon = Lottery.query.filter(
            Lottery.status == 'published',
            Lottery.draw_time >= now,
            Lottery.draw_time <= now + timedelta(minutes=10),
        ).count()
        add_item(
            '抽奖即将开奖',
            due_soon,
            'lottery_admin.index',
            desc='10分钟内有抽奖到期',
            icon='timer',
        )

    if user.is_admin:
        add_item(
            '提现待审核',
            WithdrawRequest.query.filter(WithdrawRequest.status == 'pending').count(),
            'finance.withdraw_list',
            desc='需要管理员审核提现',
            icon='badge-dollar-sign',
            status='pending',
        )

    if user.is_god:
        add_item(
            '我的待确认订单',
            Order.query.filter(
                Order.boss_id == user.id,
                Order.status == 'pending_confirm'
            ).count(),
            'orders.index',
            desc='请确认结单并完成支付',
            icon='circle-check-big',
            status='pending_confirm',
        )

    if user.is_player:
        add_item(
            '我的待申报订单',
            Order.query.filter(
                Order.player_id == user.id,
                Order.status == 'pending_report'
            ).count(),
            'orders.index',
            desc='请尽快申报时长',
            icon='notebook-pen',
            status='pending_report',
        )
        add_item(
            '我的提现审核中',
            WithdrawRequest.query.filter(
                WithdrawRequest.user_id == user.id,
                WithdrawRequest.status == 'pending'
            ).count(),
            'finance.my_wallet',
            desc='提现处理中',
            icon='hourglass',
        )

    items.sort(key=lambda x: x['count'], reverse=True)
    total = sum(item['count'] for item in items)
    return {
        'total': int(total),
        'items': items[:8],  # 顶部下拉最多展示8条，避免过高
    }
