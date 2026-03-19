"""
AI 助理小呢 — 意图识别 + 安全查询函数
根据用户消息中的关键词，自动执行对应的数据库查询，
将结果以文本形式注入到 AI 的上下文中。
"""
import re
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import func, desc

from app.extensions import db
from app.models.user import User
from app.models.order import Order
from app.models.gift import GiftOrder
from app.models.finance import BalanceLog, CommissionLog, WithdrawRequest


# ============================================================
# 意图定义: (关键词列表, 查询函数, 需要管理员权限)
# ============================================================

INTENTS = []


def _register(keywords, admin_only=True):
    """装饰器：注册一个意图"""
    def decorator(fn):
        INTENTS.append({
            'keywords': keywords,
            'handler': fn,
            'admin_only': admin_only,
        })
        return fn
    return decorator


# ---- 管理员/客服可用的查询 ----

@_register(['今日订单', '今天订单', '今天下单', '今日下单', '今天的订单', '今天有多少订单', '今天几个订单', '今天有多少单'], admin_only=True)
def query_today_orders(user, msg):
    """今日订单列表"""
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    orders = Order.query.filter(Order.created_at >= today).order_by(desc(Order.created_at)).limit(50).all()
    if not orders:
        return '📋 今日暂无订单'
    lines = ['📋 今日订单列表:']
    for o in orders:
        boss = (o.boss.nickname or o.boss.username) if o.boss else '未知'
        player = (o.player.nickname or o.player.username) if o.player else '待分配'
        project = o.project_item.name if o.project_item else '未知'
        lines.append(f'  · {o.order_no} | 老板:{boss} | 陪玩:{player} | 项目:{project} | ¥{o.boss_pay} | {o.status_label}')
    return '\n'.join(lines)


@_register(['这两天', '近两天', '最近两天', '昨天', '前两天', '两天订单'], admin_only=True)
def query_recent_days_orders(user, msg):
    """最近2天订单列表"""
    two_days_ago = datetime.utcnow() - timedelta(days=2)
    orders = Order.query.filter(Order.created_at >= two_days_ago).order_by(desc(Order.created_at)).limit(50).all()
    if not orders:
        return '📋 最近两天暂无订单'
    lines = [f'📋 最近两天订单 (共{len(orders)}单):']
    for o in orders:
        boss = (o.boss.nickname or o.boss.username) if o.boss else '未知'
        player = (o.player.nickname or o.player.username) if o.player else '待分配'
        project = o.project_item.name if o.project_item else '未知'
        date = o.created_at.strftime('%m-%d %H:%M') if o.created_at else ''
        lines.append(f'  · {o.order_no} | 老板:{boss} | 陪玩:{player} | {project} | ¥{o.boss_pay} | {o.status_label} | {date}')
    return '\n'.join(lines)


@_register(['本周订单', '这周订单', '一周订单', '近7天', '最近7天', '近一周'], admin_only=True)
def query_week_orders(user, msg):
    """近7天订单统计"""
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    orders = Order.query.filter(Order.created_at >= week_ago).all()
    if not orders:
        return '📊 近7天无订单'

    total_count = len(orders)
    total_amount = sum(float(o.boss_pay or 0) for o in orders)
    by_status = {}
    for o in orders:
        by_status[o.status_label] = by_status.get(o.status_label, 0) + 1

    lines = [f'📊 近7天订单统计:']
    lines.append(f'  · 总订单数: {total_count}')
    lines.append(f'  · 总金额: ¥{total_amount:.2f}')
    for s, c in by_status.items():
        lines.append(f'  · {s}: {c}单')
    return '\n'.join(lines)


@_register(['本月订单', '这个月订单', '月度订单'], admin_only=True)
def query_month_orders(user, msg):
    """本月订单统计"""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    orders = Order.query.filter(Order.created_at >= month_start).all()
    if not orders:
        return '📊 本月暂无订单'

    total_count = len(orders)
    total_amount = sum(float(o.boss_pay or 0) for o in orders)
    lines = [f'📊 本月订单统计:']
    lines.append(f'  · 总订单数: {total_count}')
    lines.append(f'  · 总金额: ¥{total_amount:.2f}')
    return '\n'.join(lines)


@_register(['待处理', '待审核', '未处理', '待确认订单'], admin_only=True)
def query_pending(user, msg):
    """待处理事项"""
    pending_orders = Order.query.filter(Order.status.in_(['pending_report', 'pending_confirm'])).all()
    frozen_orders = Order.query.filter(Order.freeze_status == 'frozen', Order.status == 'paid').all()
    pending_wd = WithdrawRequest.query.filter_by(status='pending').all()

    lines = ['⏳ 待处理事项汇总:']
    lines.append(f'  · 待申报/确认订单: {len(pending_orders)}')
    lines.append(f'  · 冻结中订单: {len(frozen_orders)}')
    lines.append(f'  · 待审提现: {len(pending_wd)}')

    if pending_wd:
        lines.append('\n💸 待审提现详情:')
        for w in pending_wd[:10]:
            name = (w.user.nickname or w.user.username) if w.user else '未知'
            lines.append(f'  · {name} 申请提现 ¥{w.amount} ({w.payment_method}) {w.created_at.strftime("%m-%d %H:%M") if w.created_at else ""}')

    return '\n'.join(lines)


@_register(['冻结订单', '解冻', '被冻结'], admin_only=True)
def query_frozen(user, msg):
    """冻结订单列表"""
    orders = Order.query.filter(Order.freeze_status == 'frozen').order_by(desc(Order.created_at)).limit(20).all()
    if not orders:
        return '✅ 当前没有冻结中的订单'
    lines = ['❄️ 冻结中订单:']
    for o in orders:
        boss = (o.boss.nickname or o.boss.username) if o.boss else '未知'
        player = (o.player.nickname or o.player.username) if o.player else '未知'
        lines.append(f'  · {o.order_no} | 老板:{boss} | 陪玩:{player} | ¥{o.boss_pay} | {o.status_label}')
    return '\n'.join(lines)


@_register(['用户数', '总用户', '注册用户', '有多少用户', '多少人'], admin_only=True)
def query_user_stats(user, msg):
    """用户统计"""
    total = User.query.count()
    gods = User.query.filter(User.role == 'god').count()
    players = User.query.filter(User.role == 'player').count()
    staff = User.query.filter(User.role == 'staff').count()
    admins = User.query.filter(User.role.in_(['admin', 'superadmin'])).count()

    return f"""👥 用户统计:
  · 总用户数: {total}
  · 老板: {gods}
  · 陪玩: {players}
  · 客服: {staff}
  · 管理员: {admins}"""


@_register(['查找用户', '查用户', '找用户', '搜索用户', '用户信息'], admin_only=True)
def query_user_lookup(user, msg):
    """按名字查找用户"""
    # 提取查询名字（去掉查询关键词后剩下的文本）
    clean = re.sub(r'(查找|查|找|搜索|搜|看看|看下|用户信息|用户)', '', msg).strip()
    if not clean:
        return '🔍 请告诉我要查找的用户名，例如"查找用户 小明"'

    users = User.query.filter(
        db.or_(
            User.nickname.ilike(f'%{clean}%'),
            User.username.ilike(f'%{clean}%'),
            User.user_code.ilike(f'%{clean}%'),
        )
    ).limit(10).all()

    if not users:
        return f'🔍 没有找到名字包含"{clean}"的用户'

    lines = [f'🔍 搜索"{clean}"结果:']
    for u in users:
        name = u.nickname or u.username
        lines.append(f'  · {name} (编号:{u.user_code or "-"}, 角色:{u.role_name}, 嗯呢币:{u.m_coin}, 小猪粮:{u.m_bean})')
    return '\n'.join(lines)


@_register(['充值记录', '充值流水', '充值统计', '充值总额'], admin_only=True)
def query_recharge_stats(user, msg):
    """充值统计"""
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    today_total = db.session.query(func.sum(BalanceLog.amount)).filter(
        BalanceLog.change_type == 'recharge',
        BalanceLog.created_at >= today,
    ).scalar() or 0

    month_total = db.session.query(func.sum(BalanceLog.amount)).filter(
        BalanceLog.change_type == 'recharge',
        BalanceLog.created_at >= month_start,
    ).scalar() or 0

    all_total = db.session.query(func.sum(BalanceLog.amount)).filter(
        BalanceLog.change_type == 'recharge',
    ).scalar() or 0

    return f"""💰 充值统计:
  · 今日充值: ¥{float(today_total):.2f}
  · 本月充值: ¥{float(month_total):.2f}
  · 历史总充值: ¥{float(all_total):.2f}"""


@_register(['提现记录', '提现流水', '提现统计'], admin_only=True)
def query_withdraw_stats(user, msg):
    """提现统计"""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    month_total = db.session.query(func.sum(WithdrawRequest.amount)).filter(
        WithdrawRequest.status == 'paid',
        WithdrawRequest.paid_at >= month_start,
    ).scalar() or 0

    pending = db.session.query(func.sum(WithdrawRequest.amount)).filter(
        WithdrawRequest.status == 'pending',
    ).scalar() or 0

    return f"""💸 提现统计:
  · 本月已付提现: ¥{float(month_total):.2f}
  · 待审提现总额: ¥{float(pending):.2f}"""


@_register(['排行', '排名', '谁最多', '谁充值最多', '消费最多', '前几名'], admin_only=True)
def query_rankings(user, msg):
    """消费/充值排行"""
    top_bosses = db.session.query(
        Order.boss_id,
        func.count(Order.id).label('cnt'),
        func.sum(Order.boss_pay).label('total')
    ).filter(Order.status == 'paid').group_by(Order.boss_id).order_by(desc('total')).limit(5).all()

    if not top_bosses:
        return '🏆 暂无排行数据'

    lines = ['🏆 老板消费排行 TOP5:']
    for i, (boss_id, cnt, total) in enumerate(top_bosses, 1):
        u = User.query.get(boss_id)
        name = (u.nickname or u.username) if u else '未知'
        lines.append(f'  {i}. {name} — {cnt}单, 总消费 ¥{float(total or 0):.2f}')
    return '\n'.join(lines)


# ---- 所有用户可用的查询 ----

@_register(['我的余额', '我的钱', '余额查询', '我还有多少', '我还剩'], admin_only=False)
def query_my_balance(user, msg):
    """当前用户余额"""
    lines = [f'💰 {user.nickname or user.username} 的账户:']
    if user.is_god or user.is_admin:
        lines.append(f'  · 嗯呢币: {user.m_coin}')
        lines.append(f'  · 赠金: {user.m_coin_gift}')
    if user.is_player or user.is_admin:
        lines.append(f'  · 小猪粮: {user.m_bean}')
        lines.append(f'  · 冻结小猪粮: {user.m_bean_frozen}')
    return '\n'.join(lines)


@_register(['我的订单', '我下的单', '订单记录', '订单历史'], admin_only=False)
def query_my_orders(user, msg):
    """当前用户订单"""
    if user.is_god:
        orders = Order.query.filter_by(boss_id=user.id).order_by(desc(Order.created_at)).limit(10).all()
    elif user.is_player:
        orders = Order.query.filter_by(player_id=user.id).order_by(desc(Order.created_at)).limit(10).all()
    else:
        return '📋 无法查询您的订单'

    if not orders:
        return '📋 暂无订单记录'

    lines = ['📋 最近订单:']
    for o in orders:
        project = o.project_item.name if o.project_item else '未知'
        date = o.created_at.strftime('%m-%d %H:%M') if o.created_at else ''
        lines.append(f'  · {o.order_no} | {project} | ¥{o.boss_pay} | {o.status_label} | {date}')
    return '\n'.join(lines)


# ============================================================
# 主入口: 对用户消息进行意图匹配并执行查询
# ============================================================

def detect_and_query(user, message):
    """
    分析用户消息，匹配意图并执行查询。
    返回: 额外上下文文本（可能为空字符串）
    """
    is_admin = user.is_admin or user.has_role('staff')
    results = []

    for intent in INTENTS:
        # 权限检查
        if intent['admin_only'] and not is_admin:
            continue

        # 关键词匹配
        matched = any(kw in message for kw in intent['keywords'])
        if matched:
            try:
                result = intent['handler'](user, message)
                if result:
                    results.append(result)
            except Exception as e:
                results.append(f'(查询出错: {str(e)[:100]})')

    if not results:
        return ''

    return '\n\n--- 🔍 查询结果 ---\n\n' + '\n\n'.join(results)
