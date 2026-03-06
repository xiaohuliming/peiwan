from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import random
import string

from app.extensions import db
from app.models.order import Order
from app.models.project import ProjectItem
from app.models.user import User
from app.models.finance import BalanceLog, CommissionLog
from app.services.log_service import log_operation
from flask_login import current_user

NO_VIP_DISCOUNT = Decimal('100')


def _get_boss_discount_percent(boss):
    """获取老板折扣百分比（100=无折扣，90=9折）。"""
    try:
        discount = Decimal(str(getattr(boss, 'vip_discount', NO_VIP_DISCOUNT) or NO_VIP_DISCOUNT))
    except Exception:
        discount = NO_VIP_DISCOUNT
    if discount <= 0:
        return NO_VIP_DISCOUNT
    if discount > Decimal('100'):
        return Decimal('100')
    return discount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _calc_order_amounts_with_discount_subsidy(subtotal, commission_rate, discount_percent):
    """
    计算订单金额（老板折扣由店铺承担）：
    - 老板实付 total_price = subtotal * 折扣
    - 陪玩收益 player_earning = subtotal * 佣金比例（不受折扣影响）
    - 店铺分成 shop_earning = total_price - player_earning（可能为负，表示店铺补贴）
    """
    subtotal_dec = Decimal(str(subtotal))
    commission_dec = Decimal(str(commission_rate))
    discount_dec = Decimal(str(discount_percent or NO_VIP_DISCOUNT)) / Decimal('100')

    total_price = (subtotal_dec * discount_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    player_earning = (subtotal_dec * commission_dec / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    shop_earning = (total_price - player_earning).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return total_price, player_earning, shop_earning


def _get_operator_id():
    try:
        if current_user and current_user.is_authenticated:
            return current_user.id
    except Exception:
        pass
    return None

def generate_order_no():
    """生成订单号: YYYYMMDDHHmmss + 4位随机数"""
    now = datetime.now()
    rand = ''.join(random.choices(string.digits, k=4))
    return now.strftime('%Y%m%d%H%M%S') + rand


def calc_duration_hours(start_time, end_time):
    """计算时长 (小时), >15分钟余数算0.5h"""
    delta = end_time - start_time
    total_minutes = delta.total_seconds() / 60
    full_hours = int(total_minutes // 60)
    remainder = total_minutes % 60
    if remainder > 15:
        return Decimal(str(full_hours)) + Decimal('0.5')
    return Decimal(str(full_hours))


def _is_half_hour_step(duration: Decimal) -> bool:
    """仅允许 0.5 小时粒度：1, 1.5, 2, 2.5 ..."""
    twice = duration * Decimal('2')
    return twice == twice.to_integral_value()


def deduct_boss_balance(boss, amount, order_no):
    """
    扣除老板余额: 优先扣m_coin, 再扣m_coin_gift
    同时记录消费日志和经验值
    返回: True/False
    """
    amount = Decimal(str(amount))
    total_available = boss.m_coin + boss.m_coin_gift

    if total_available < amount:
        return False

    # 优先扣 m_coin
    if boss.m_coin >= amount:
        boss.m_coin -= amount
        coin_deducted = amount
    else:
        coin_deducted = boss.m_coin
        gift_deducted = amount - boss.m_coin
        boss.m_coin = Decimal('0')
        boss.m_coin_gift -= gift_deducted

    # 记录消费日志
    log = BalanceLog(
        user_id=boss.id,
        change_type='consume',
        amount=-amount,
        balance_after=boss.m_coin + boss.m_coin_gift,
        reason=f'订单 {order_no} 消费'
    )
    db.session.add(log)

    # m_coin消费增加经验 (1:1)
    boss.experience += int(coin_deducted)

    # 检查VIP升级
    from app.services.vip_service import check_and_upgrade
    check_and_upgrade(boss)

    # KOOK 私信通知（老板消费）
    try:
        from app.services.kook_service import push_boss_consume_notice
        push_boss_consume_notice(
            boss,
            amount,
            reason=log.reason,
        )
    except Exception:
        pass

    return True


def refund_boss_balance(boss, amount, order_no):
    """退还老板嗯呢币"""
    amount = Decimal(str(amount))
    boss.m_coin += amount

    log = BalanceLog(
        user_id=boss.id,
        change_type='refund',
        amount=amount,
        balance_after=boss.m_coin + boss.m_coin_gift,
        reason=f'订单 {order_no} 退款'
    )
    db.session.add(log)


def award_player_earning(player, amount, order):
    """发放陪玩小猪粮收益"""
    amount = Decimal(str(amount))
    player.m_bean += amount

    log = CommissionLog(
        user_id=player.id,
        change_type='order_income',
        amount=amount,
        balance_after=player.m_bean,
        order_id=order.id,
        reason=f'订单 {order.order_no} 收益'
    )
    db.session.add(log)


def deduct_player_earning(player, amount, order):
    """扣回陪玩小猪粮 (退款时)"""
    amount = Decimal(str(amount))
    player.m_bean -= amount
    if player.m_bean < 0:
        player.m_bean = Decimal('0')

    log = CommissionLog(
        user_id=player.id,
        change_type='refund_deduct',
        amount=-amount,
        balance_after=player.m_bean,
        order_id=order.id,
        reason=f'订单 {order.order_no} 退款扣回'
    )
    db.session.add(log)


def create_normal_order(boss, player, project_item, price_tier, staff,
                        extra_price=0, addon_desc=None, addon_price=0, remark=None):
    """
    创建常规陪玩订单 (状态: pending_report)
    不即时扣款, 等老板确认时扣款
    """
    base_price = Decimal(str(project_item.get_price_by_tier(price_tier) or 0))
    extra_price_dec = Decimal(str(extra_price))
    addon_price_dec = Decimal(str(addon_price))
    commission_rate = project_item.commission_rate
    boss_discount = _get_boss_discount_percent(boss)

    # 创建前余额校验：按 1 小时/局的最低可扣金额预校验
    min_subtotal = (base_price + extra_price_dec + addon_price_dec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    min_required, _, _ = _calc_order_amounts_with_discount_subsidy(
        subtotal=min_subtotal,
        commission_rate=commission_rate,
        discount_percent=boss_discount,
    )
    total_available = boss.m_coin + boss.m_coin_gift
    if total_available < min_required:
        return None, f'老板余额不足，至少需要 {min_required} 嗯呢币 才可派单'

    order = Order(
        order_no=generate_order_no(),
        boss_id=boss.id,
        player_id=player.id,
        staff_id=staff.id if staff else None,
        project_item_id=project_item.id,
        price_tier=price_tier,
        base_price=base_price,
        extra_price=extra_price_dec,
        addon_desc=addon_desc,
        addon_price=addon_price_dec,
        boss_discount=boss_discount,
        commission_rate=commission_rate,
        order_type='normal',
        status='pending_report',
        remark=remark,
    )
    db.session.add(order)
    db.session.flush()
    
    log_operation(_get_operator_id(), 'order_create_normal', 'order', order.id,
                  f'创建常规订单 {order.order_no}, 价格档位: {price_tier}')
    return order, None


def create_escort_order(boss, player, project_item, price_tier, staff,
                        duration, extra_price=0, addon_desc=None, addon_price=0, remark=None):
    """
    创建护航/代练订单 (即时扣款+冻结佣金)
    """
    base_price = project_item.get_price_by_tier(price_tier)
    commission_rate = project_item.commission_rate
    boss_discount = _get_boss_discount_percent(boss)
    unit_price = Decimal(str(base_price)) + Decimal(str(extra_price))
    duration_dec = Decimal(str(duration))
    subtotal = unit_price * duration_dec + Decimal(str(addon_price))
    total_price, player_earning, shop_earning = _calc_order_amounts_with_discount_subsidy(
        subtotal=subtotal,
        commission_rate=commission_rate,
        discount_percent=boss_discount,
    )

    # 验证余额
    total_available = boss.m_coin + boss.m_coin_gift
    if total_available < total_price:
        return None, '老板余额不足'

    order = Order(
        order_no=generate_order_no(),
        boss_id=boss.id,
        player_id=player.id,
        staff_id=staff.id if staff else None,
        project_item_id=project_item.id,
        price_tier=price_tier,
        base_price=base_price,
        extra_price=Decimal(str(extra_price)),
        addon_desc=addon_desc,
        addon_price=Decimal(str(addon_price)),
        boss_discount=boss_discount,
        commission_rate=commission_rate,
        total_price=total_price,
        player_earning=player_earning,
        shop_earning=shop_earning,
        order_type=project_item.project_type,
        duration=duration_dec,
        status='pending_pay',
        pay_time=datetime.utcnow(),
        remark=remark,
    )
    db.session.add(order)
    db.session.flush()
    
    log_operation(_get_operator_id(), 'order_create_escort', 'order', order.id,
                  f'创建护航/代练订单 {order.order_no}, 总价: {total_price}')
    
    # 即时扣款
    if not deduct_boss_balance(boss, total_price, order.order_no):
        db.session.rollback()
        return None, '扣款失败'

    # 冻结陪玩佣金
    player.m_bean_frozen += player_earning

    return order, None


def report_order(order, duration_hours, operator_id=None):
    """
    陪玩申报时长(小时), 计算总价
    状态: pending_report/pending_confirm → pending_confirm
    """
    if order.status not in ('pending_report', 'pending_confirm'):
        return False, '订单状态不正确'

    try:
        duration = Decimal(str(duration_hours or 0))
    except Exception:
        return False, '时长格式错误'

    if duration <= 0:
        return False, '时长必须大于0'
    if not _is_half_hour_step(duration):
        return False, '时长仅支持整数或0.5小时（如 0.5、1、1.5、2.5）'

    unit_price = Decimal(str(order.base_price)) + Decimal(str(order.extra_price))
    subtotal = unit_price * duration + Decimal(str(order.addon_price))
    boss_discount = _get_boss_discount_percent(order.boss)
    total_price, player_earning, shop_earning = _calc_order_amounts_with_discount_subsidy(
        subtotal=subtotal,
        commission_rate=order.commission_rate,
        discount_percent=boss_discount,
    )

    order.duration = duration
    order.total_price = total_price
    order.player_earning = player_earning
    order.shop_earning = shop_earning
    now = datetime.utcnow()
    order.fill_time = now
    order.report_time = now
    order.status = 'pending_confirm'
    order.boss_discount = boss_discount
    order.auto_confirm_at = now + timedelta(hours=24)

    log_operation(operator_id or _get_operator_id(), 'order_report', 'order', order.id,
                  f'陪玩申报订单 {order.order_no}, 时长: {duration}h, 总价: {total_price}')

    return True, None


def confirm_order(order, operator_id=None):
    """
    老板确认 / 24h自动确认
    先扣老板余额，再发放佣金，状态 → paid
    """
    if order.status != 'pending_confirm':
        return False, '订单状态不正确'

    if order.is_frozen:
        return False, '订单已冻结, 无法确认'

    # 常规订单在确认时扣款
    boss = order.boss
    if not deduct_boss_balance(boss, order.total_price, order.order_no):
        return False, '老板余额不足，无法确认订单'

    player = order.player
    award_player_earning(player, order.player_earning, order)

    order.status = 'paid'
    order.confirm_time = datetime.utcnow()
    order.pay_time = datetime.utcnow()

    log_operation(operator_id or _get_operator_id(), 'order_confirm', 'order', order.id,
                  f'订单 {order.order_no} 已确认, 发放佣金: {order.player_earning}')

    return True, None


def settle_escort_order(order):
    """
    结算护航/代练订单:
    将冻结佣金(m_bean_frozen)转为可用小猪粮(m_bean), 状态 → paid
    """
    if order.status != 'pending_pay':
        return False, '订单状态不正确，仅待结算订单可结算'

    if order.order_type not in ('escort', 'training'):
        return False, '仅护航/代练订单支持此操作'

    if order.is_frozen:
        return False, '订单已冻结，请先解冻后再结算'

    player = order.player
    earning = order.player_earning

    # 从冻结转为可用
    if player.m_bean_frozen >= earning:
        player.m_bean_frozen -= earning
    else:
        player.m_bean_frozen = Decimal('0')

    award_player_earning(player, earning, order)

    order.status = 'paid'
    order.confirm_time = datetime.utcnow()

    log_operation(_get_operator_id(), 'order_settle', 'order', order.id,
                  f'订单 {order.order_no} 结算完成, 佣金: {earning}')

    return True, None


def refund_order(order):
    """
    退款: 退老板嗯呢币, 扣回陪玩小猪粮
    """
    if order.status not in ('pending_pay', 'paid'):
        return False, '当前状态不可退款'

    boss = order.boss
    player = order.player

    # 退老板
    refund_boss_balance(boss, order.total_price, order.order_no)

    # 如果已经发了佣金, 扣回
    if order.status == 'paid':
        deduct_player_earning(player, order.player_earning, order)

    # 护航/代练: 解冻冻结的佣金
    if order.order_type in ('escort', 'training') and order.status == 'pending_pay':
        if player.m_bean_frozen >= order.player_earning:
            player.m_bean_frozen -= order.player_earning
        else:
            player.m_bean_frozen = Decimal('0')

    order.status = 'refunded'
    order.refund_time = datetime.utcnow()
    order.freeze_status = 'normal'

    log_operation(_get_operator_id(), 'order_refund', 'order', order.id,
                  f'订单 {order.order_no} 已退款, 退还: {order.total_price}')

    return True, None


def freeze_order(order):
    """冻结订单"""
    if order.freeze_status == 'frozen':
        return False, '订单已冻结'
    order.freeze_status = 'frozen'
    log_operation(_get_operator_id(), 'order_freeze', 'order', order.id, f'冻结订单 {order.order_no}')
    return True, None


def unfreeze_order(order):
    """解冻订单"""
    if order.freeze_status != 'frozen':
        return False, '订单未冻结'
    order.freeze_status = 'normal'
    log_operation(_get_operator_id(), 'order_unfreeze', 'order', order.id, f'解冻订单 {order.order_no}')
    return True, None


def delete_order(order, operator_id=None):
    """
    手动删除订单:
    1) 仅允许删除未付款订单: pending_report / pending_confirm
    2) 删除不触发资金变动
    3) 删除订单本身
    """
    if order.status not in ('pending_report', 'pending_confirm'):
        return False, '仅未付款订单可删除，已支付订单请走退款流程'

    # 防止历史脏数据: 若已有资金流水，不允许删除
    has_balance_flow = BalanceLog.query.filter(
        BalanceLog.change_type.in_(['consume', 'refund']),
        BalanceLog.reason.ilike(f'%{order.order_no}%'),
    ).first()
    has_commission_flow = CommissionLog.query.filter_by(order_id=order.id).first()
    if has_balance_flow or has_commission_flow:
        return False, '该订单已产生资金流水，不能删除，请走退款流程'

    order_id = order.id
    order_no = order.order_no

    db.session.delete(order)

    log_operation(operator_id or _get_operator_id(), 'order_delete', 'order', order_id, f'删除订单 {order_no}')
    return True, None
