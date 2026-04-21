from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import random
import string

from app.extensions import db
from app.models.order import Order
from app.models.finance import BalanceLog, CommissionLog
from app.services.frozen_balance_service import (
    adjust_legacy_frozen_cache,
    get_user_frozen_breakdown,
)
from app.services.log_service import log_operation
from flask_login import current_user

NO_VIP_DISCOUNT = Decimal('100')
VIP_DISCOUNT_EXEMPT_ORDER_TYPES = {'training'}  # 代练/代肝订单不参与老板 VIP 折扣
STAFF_COMMISSION_NORMAL = Decimal('1')      # 常规陪玩: 1元/单
STAFF_COMMISSION_RATE = Decimal('0.01')     # 护航/代练/礼物: 1%


def award_staff_commission(staff, amount, order=None, reason=''):
    """客服提成仅做平台绩效统计，不再写入用户余额或流水。"""
    return


def _get_order_staff_refund_amount(order):
    """客服提成不入账，退款无需扣回客服余额。"""
    return Decimal('0.00')


def deduct_staff_commission(staff, amount, order, reason=''):
    """客服提成不入账，退款无需扣回客服余额。"""
    return Decimal('0.00')


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


def _get_order_discount_percent(boss, order_type='normal'):
    """根据订单类型获取折扣；部分类型固定不参与 VIP 折扣。"""
    if str(order_type or '').lower() in VIP_DISCOUNT_EXEMPT_ORDER_TYPES:
        return NO_VIP_DISCOUNT
    return _get_boss_discount_percent(boss)


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
    返回: (success, coin_deducted, gift_deducted)
    """
    amount = Decimal(str(amount))
    total_available = boss.m_coin + boss.m_coin_gift

    if total_available < amount:
        return False, Decimal('0'), Decimal('0')

    # 优先扣 m_coin
    if boss.m_coin >= amount:
        coin_deducted = amount
        gift_deducted = Decimal('0')
        boss.m_coin -= amount
    else:
        coin_deducted = boss.m_coin
        gift_deducted = amount - boss.m_coin
        boss.m_coin = Decimal('0')
        boss.m_coin_gift -= gift_deducted

    # 记录消费日志（含拆分明细）
    log = BalanceLog(
        user_id=boss.id,
        change_type='consume',
        amount=-amount,
        balance_after=boss.m_coin + boss.m_coin_gift,
        reason=f'订单 {order_no} 消费 (币:{coin_deducted}, 赠:{gift_deducted})'
    )
    db.session.add(log)

    # m_coin消费增加经验
    from app.services.vip_service import apply_consume_experience, check_and_upgrade
    apply_consume_experience(boss, coin_deducted)

    # 检查VIP升级
    check_and_upgrade(boss)

    # KOOK 私信通知
    try:
        from app.services.kook_service import push_boss_consume_notice
        push_boss_consume_notice(
            boss,
            amount,
            reason=log.reason,
        )
    except Exception:
        pass

    return True, coin_deducted, gift_deducted


def _quantize_money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _deduct_boss_balance_silent(boss, amount):
    """
    仅扣老板余额，不记账不发通知。
    返回: (success, coin_deducted, gift_deducted)
    """
    amount = _quantize_money(amount)
    if amount <= 0:
        return True, Decimal('0.00'), Decimal('0.00')

    total_available = _quantize_money(boss.m_coin) + _quantize_money(boss.m_coin_gift)
    if total_available < amount:
        return False, Decimal('0.00'), Decimal('0.00')

    if _quantize_money(boss.m_coin) >= amount:
        coin_deducted = amount
        gift_deducted = Decimal('0.00')
        boss.m_coin = _quantize_money(boss.m_coin) - amount
    else:
        coin_deducted = _quantize_money(boss.m_coin)
        gift_deducted = amount - coin_deducted
        boss.m_coin = Decimal('0.00')
        boss.m_coin_gift = _quantize_money(boss.m_coin_gift) - gift_deducted

    return True, coin_deducted, gift_deducted


def _release_order_hold(order, reason='订单解冻释放'):
    """把订单冻结金额退回老板钱包（原路退回 m_coin / m_coin_gift）"""
    boss = order.boss
    hold_coin = _quantize_money(order.boss_hold_coin)
    hold_gift = _quantize_money(order.boss_hold_gift)
    release_total = hold_coin + hold_gift
    if release_total <= 0:
        return Decimal('0.00')

    boss.m_coin = _quantize_money(boss.m_coin) + hold_coin
    boss.m_coin_gift = _quantize_money(boss.m_coin_gift) + hold_gift
    order.boss_hold_coin = Decimal('0.00')
    order.boss_hold_gift = Decimal('0.00')

    db.session.add(BalanceLog(
        user_id=boss.id,
        change_type='order_unhold',
        amount=release_total,
        balance_after=_quantize_money(boss.m_coin) + _quantize_money(boss.m_coin_gift),
        reason=f'订单 {order.order_no} {reason}'
    ))
    return release_total


def _adjust_order_hold(order, target_total):
    """
    将订单冻结金额调整到 target_total（用于申报/改报单）。
    返回: (ok, err)
    """
    boss = order.boss
    target_total = _quantize_money(target_total)
    hold_coin = _quantize_money(order.boss_hold_coin)
    hold_gift = _quantize_money(order.boss_hold_gift)
    current_hold = hold_coin + hold_gift
    delta = target_total - current_hold

    if delta > 0:
        ok, coin_add, gift_add = _deduct_boss_balance_silent(boss, delta)
        if not ok:
            return False, '老板余额不足，无法冻结申报金额'

        order.boss_hold_coin = hold_coin + coin_add
        order.boss_hold_gift = hold_gift + gift_add
        db.session.add(BalanceLog(
            user_id=boss.id,
            change_type='order_hold',
            amount=-delta,
            balance_after=_quantize_money(boss.m_coin) + _quantize_money(boss.m_coin_gift),
            reason=f'订单 {order.order_no} 申报冻结'
        ))
        return True, None

    if delta < 0:
        release_need = -delta
        release_coin = min(hold_coin, release_need)
        release_need -= release_coin
        release_gift = min(hold_gift, release_need)

        order.boss_hold_coin = hold_coin - release_coin
        order.boss_hold_gift = hold_gift - release_gift
        boss.m_coin = _quantize_money(boss.m_coin) + release_coin
        boss.m_coin_gift = _quantize_money(boss.m_coin_gift) + release_gift

        db.session.add(BalanceLog(
            user_id=boss.id,
            change_type='order_unhold',
            amount=release_coin + release_gift,
            balance_after=_quantize_money(boss.m_coin) + _quantize_money(boss.m_coin_gift),
            reason=f'订单 {order.order_no} 申报调整解冻'
        ))
        return True, None

    return True, None


def refund_boss_balance(boss, amount, order_no, refund_coin=None, refund_gift=None):
    """
    退还老板余额（支持原路退回）。
    如果提供了 refund_coin / refund_gift 则按拆分退回；
    否则全部退到 m_coin（兼容历史调用）。
    """
    amount = Decimal(str(amount))
    if refund_coin is not None and refund_gift is not None:
        coin_back = _quantize_money(refund_coin)
        gift_back = _quantize_money(refund_gift)
    else:
        coin_back = amount
        gift_back = Decimal('0')

    boss.m_coin += coin_back
    boss.m_coin_gift += gift_back

    log = BalanceLog(
        user_id=boss.id,
        change_type='refund',
        amount=amount,
        balance_after=boss.m_coin + boss.m_coin_gift,
        reason=f'订单 {order_no} 退款 (币:{coin_back}, 赠:{gift_back})'
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
    """扣回陪玩小猪粮 (退款时) — 余额不足时拒绝而非静默清零"""
    amount = Decimal(str(amount))
    if player.m_bean < amount:
        shortfall = (amount - player.m_bean).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        raise ValueError(f'deduct_player_earning: shortfall {shortfall}')

    player.m_bean -= amount

    log = CommissionLog(
        user_id=player.id,
        change_type='refund_deduct',
        amount=-amount,
        balance_after=player.m_bean,
        order_id=order.id,
        reason=f'订单 {order.order_no} 退款扣回'
    )
    db.session.add(log)


def deduct_player_earning_frozen_first(player, amount, order):
    """退款扣回陪玩收益: 优先扣实时冻结收益(订单/礼物), 不足再扣可用小猪粮"""
    amount = _quantize_money(amount)
    if amount <= 0:
        return Decimal('0'), Decimal('0')

    frozen_breakdown = get_user_frozen_breakdown(player)
    remaining = amount
    frozen_deduct = min(frozen_breakdown['earning_frozen'], remaining)
    if frozen_deduct > 0:
        # 兼容历史字段：仅同步 legacy cache，真实冻结金额以后续明细实时聚合为准。
        adjust_legacy_frozen_cache(player, -frozen_deduct)
    remaining -= frozen_deduct

    bean_deduct = min(_quantize_money(player.m_bean), remaining)
    player.m_bean = _quantize_money(player.m_bean) - bean_deduct
    remaining -= bean_deduct

    total_deduct = frozen_deduct + bean_deduct
    log = CommissionLog(
        user_id=player.id,
        change_type='refund_deduct',
        amount=-total_deduct,
        balance_after=player.m_bean,
        order_id=order.id,
        reason=(
            f'订单 {order.order_no} 退款扣回'
            f' (冻结:{frozen_deduct}, 可用:{bean_deduct}, 未扣回:{remaining})'
        )
    )
    db.session.add(log)
    return total_deduct, remaining


def create_normal_order(boss, player, project_item, price_tier, staff,
                        extra_price=0, addon_desc=None, addon_price=0, remark=None):
    """
    创建常规陪玩订单 (状态: pending_report)
    不在创建时扣款，陪玩申报后先冻结，老板确认时再记消费
    """
    base_price = Decimal(str(project_item.get_price_by_tier(price_tier) or 0))
    extra_price_dec = Decimal(str(extra_price))
    addon_price_dec = Decimal(str(addon_price))
    commission_rate = player.commission_rate if player.commission_rate is not None else project_item.commission_rate
    boss_discount = _get_order_discount_percent(boss, 'normal')

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
        boss_hold_coin=Decimal('0.00'),
        boss_hold_gift=Decimal('0.00'),
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
    创建护航/代练订单:
    即时扣款 + 直接结算 + 自动冻结（无需报单）
    """
    base_price = Decimal(str(project_item.get_price_by_tier(price_tier) or 0))
    commission_rate = player.commission_rate if player.commission_rate is not None else project_item.commission_rate
    project_type = project_item.project_type or 'escort'
    boss_discount = _get_order_discount_percent(boss, project_type)
    unit_price = base_price + Decimal(str(extra_price))
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

    now = datetime.utcnow()
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
        order_type=project_type,
        duration=duration_dec,
        status='pending_pay',
        fill_time=now,
        report_time=now,
        pay_time=now,
        auto_confirm_at=None,
        remark=remark,
    )
    db.session.add(order)
    db.session.flush()

    log_operation(_get_operator_id(), 'order_create_escort', 'order', order.id,
                  f'创建护航/代练订单 {order.order_no}, 总价: {total_price}')

    # 即时扣款
    ok, coin_deducted, gift_deducted = deduct_boss_balance(boss, total_price, order.order_no)
    if not ok:
        db.session.rollback()
        return None, '扣款失败'

    # 记录嗯呢币/赠金拆分（用于原路退款）
    order.boss_hold_coin = coin_deducted
    order.boss_hold_gift = gift_deducted

    # 护航/代练冻结以后续订单明细实时聚合为准；这里仅兼容同步 legacy cache。
    adjust_legacy_frozen_cache(player, player_earning)

    # 护航/代练创建后直接结算并冻结（不经过报单）
    ok, err = settle_escort_order(order)
    if not ok:
        db.session.rollback()
        return None, err

    return order, None


def report_order(order, duration_hours, operator_id=None):
    """
    陪玩申报时长(小时), 计算总价
    - 仅常规单: pending_report/pending_confirm → pending_confirm
    - 申报时冻结老板金额（改报单自动增减冻结）
    """
    if order.order_type in ('escort', 'training'):
        return False, '护航/代练订单无需报单，创建后已自动结算并冻结'
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
    boss_discount = _get_order_discount_percent(order.boss, order.order_type)
    total_price, player_earning, shop_earning = _calc_order_amounts_with_discount_subsidy(
        subtotal=subtotal,
        commission_rate=order.commission_rate,
        discount_percent=boss_discount,
    )

    now = datetime.utcnow()

    # 申报阶段先冻结老板金额；改报单会自动增减冻结金额
    old_total = _quantize_money(order.total_price)
    order.total_price = total_price
    hold_ok, hold_err = _adjust_order_hold(order, _quantize_money(total_price))
    if not hold_ok:
        order.total_price = old_total
        return False, hold_err

    order.duration = duration
    order.player_earning = player_earning
    order.shop_earning = shop_earning
    order.fill_time = now
    order.report_time = now
    order.boss_discount = boss_discount
    order.status = 'pending_confirm'
    # 陪玩单：老板可手动确认；超 24h 未确认走自动确认
    order.auto_confirm_at = now + timedelta(hours=24)

    hold_total = _quantize_money(order.boss_hold_coin) + _quantize_money(order.boss_hold_gift)
    log_operation(operator_id or _get_operator_id(), 'order_report', 'order', order.id,
                  f'陪玩申报订单 {order.order_no}, 时长: {duration}h, 总价: {total_price}, 已冻结: {hold_total}')

    return True, None


def confirm_order(order, operator_id=None):
    """
    老板确认 / 24h自动确认
    陪玩单在申报时已冻结老板金额，确认后陪玩收益直接到账
    """
    if order.status != 'pending_confirm':
        return False, '订单状态不正确'

    if order.order_type in ('escort', 'training'):
        return False, '护航/代练订单不走确认流程'

    boss = order.boss
    total_price = _quantize_money(order.total_price)
    hold_coin = _quantize_money(order.boss_hold_coin)
    hold_gift = _quantize_money(order.boss_hold_gift)
    hold_total = hold_coin + hold_gift

    # 先吃掉冻结资金，不足部分兜底实时扣款（兼容历史数据）
    consume_from_hold = min(hold_total, total_price)
    consume_coin_from_hold = min(hold_coin, consume_from_hold)
    consume_gift_from_hold = consume_from_hold - consume_coin_from_hold
    remaining_pay = total_price - consume_from_hold

    coin_direct = Decimal('0.00')
    gift_direct = Decimal('0.00')
    if remaining_pay > 0:
        ok, coin_direct, gift_direct = _deduct_boss_balance_silent(boss, remaining_pay)
        if not ok:
            return False, '老板余额不足，无法确认订单'

    # 计算总嗯呢币/赠金消费拆分
    total_coin_consumed = consume_coin_from_hold + coin_direct
    total_gift_consumed = consume_gift_from_hold + gift_direct

    # 支付能力确认后，再落冻结金额变动，避免失败路径污染
    order.boss_hold_coin = hold_coin - consume_coin_from_hold
    order.boss_hold_gift = hold_gift - consume_gift_from_hold

    # 理论上确认后不应再残留冻结，如有残留立即退回
    if _quantize_money(order.boss_hold_coin) + _quantize_money(order.boss_hold_gift) > 0:
        _release_order_hold(order, reason='确认后自动解冻差额')

    # 确认后将 hold 字段复用为"实际支付拆分"，供退款原路退回使用
    order.boss_hold_coin = total_coin_consumed
    order.boss_hold_gift = total_gift_consumed

    db.session.add(BalanceLog(
        user_id=boss.id,
        change_type='consume',
        amount=-total_price,
        balance_after=_quantize_money(boss.m_coin) + _quantize_money(boss.m_coin_gift),
        reason=f'订单 {order.order_no} 消费 (币:{total_coin_consumed}, 赠:{total_gift_consumed})'
    ))

    # 仅真实嗯呢币消费增加经验（冻结嗯呢币 + 兜底扣款中的嗯呢币）
    from app.services.vip_service import apply_consume_experience, check_and_upgrade
    apply_consume_experience(boss, consume_coin_from_hold + coin_direct)
    check_and_upgrade(boss)

    # KOOK 私信通知（老板消费）
    try:
        from app.services.kook_service import push_boss_consume_notice
        push_boss_consume_notice(
            boss,
            total_price,
            reason=f'订单 {order.order_no} 消费',
        )
    except Exception:
        pass

    # 常规陪玩单：确认后直接给陪玩入账（不冻结）
    player = order.player
    player_earning = _quantize_money(order.player_earning)
    if player_earning > 0:
        award_player_earning(player, player_earning, order)

    order.status = 'paid'
    order.freeze_status = 'normal'
    order.confirm_time = datetime.utcnow()
    order.pay_time = datetime.utcnow()
    order.auto_confirm_at = None

    # 客服提成仅用于平台绩效统计，不写入客服余额。

    log_operation(operator_id or _get_operator_id(), 'order_confirm', 'order', order.id,
                  f'订单 {order.order_no} 已确认并自动结算, 佣金 {order.player_earning} 已到账')

    return True, None


def settle_escort_order(order):
    """
    结算护航/代练订单:
    状态 → paid，自动冻结订单，佣金以后续订单明细实时聚合为准，等待手动解冻
    """
    if order.status != 'pending_pay':
        return False, '订单状态不正确，仅待结算订单可结算'

    if order.order_type not in ('escort', 'training'):
        return False, '仅护航/代练订单支持此操作'

    if order.is_frozen:
        return False, '订单已冻结，请先解冻后再结算'

    # 佣金真实冻结来源以后续订单明细为准，不直接转为可用；等待客服手动解冻。
    order.status = 'paid'
    order.freeze_status = 'frozen'
    order.confirm_time = datetime.utcnow()

    # 客服提成仅用于平台绩效统计，不写入客服余额。

    log_operation(_get_operator_id(), 'order_settle', 'order', order.id,
                  f'订单 {order.order_no} 结算完成, 佣金 {order.player_earning} 已冻结待解冻')

    return True, None


def refund_order(order):
    """
    退款: 退老板嗯呢币, 扣回陪玩小猪粮
    """
    if order.status not in ('pending_pay', 'paid'):
        return False, '当前状态不可退款'

    boss = order.boss
    player = order.player
    player_earning = _quantize_money(order.player_earning)
    available_frozen = get_user_frozen_breakdown(player)['earning_frozen']
    available_bean = _quantize_money(player.m_bean)
    player_total_available = available_frozen + available_bean

    if player_total_available < player_earning:
        shortfall = (player_earning - player_total_available).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return False, f'退款失败：陪玩收益不足，差额 {shortfall} 小猪粮，请先补足后再退款'

    # 退老板（原路退回嗯呢币/赠金）
    refund_coin = _quantize_money(order.boss_hold_coin)
    refund_gift = _quantize_money(order.boss_hold_gift)
    # 兜底：如果拆分记录为0但订单有金额（历史数据/未走confirm路径），全部退到嗯呢币
    if refund_coin + refund_gift <= 0 and _quantize_money(order.total_price) > 0:
        refund_coin = _quantize_money(order.total_price)
        refund_gift = Decimal('0')
    refund_boss_balance(boss, order.total_price, order.order_no,
                        refund_coin=refund_coin, refund_gift=refund_gift)

    # 扣回陪玩收益（优先冻结，再可用）
    if order.status in ('pending_pay', 'paid'):
        deduct_player_earning_frozen_first(player, order.player_earning, order)

    order.status = 'refunded'
    order.refund_time = datetime.utcnow()
    order.freeze_status = 'normal'

    detail = f'订单 {order.order_no} 已退款, 退还: {order.total_price}'
    log_operation(_get_operator_id(), 'order_refund', 'order', order.id,
                  detail)

    return True, None


def freeze_order(order):
    """冻结订单"""
    if str(order.order_type or 'normal').lower() not in ('escort', 'training'):
        return False, '陪玩订单无需冻结'
    if order.freeze_status == 'frozen':
        return False, '订单已冻结'
    order.freeze_status = 'frozen'
    log_operation(_get_operator_id(), 'order_freeze', 'order', order.id, f'冻结订单 {order.order_no}')
    return True, None


def unfreeze_order(order):
    """解冻订单；若订单已结算(paid)，同时将冻结佣金释放给陪玩"""
    if order.freeze_status != 'frozen':
        return False, '订单未冻结'

    order.freeze_status = 'normal'

    # 已结算订单解冻时，释放冻结的佣金
    if order.status == 'paid' and order.player_earning > 0:
        player = order.player
        earning = _quantize_money(order.player_earning)

        already_awarded = CommissionLog.query.filter_by(
            order_id=order.id,
            change_type='order_income',
        ).first()

        if not already_awarded:
            adjust_legacy_frozen_cache(player, -earning)
            award_player_earning(player, earning, order)
            log_operation(_get_operator_id(), 'order_unfreeze', 'order', order.id,
                          f'解冻订单 {order.order_no}, 佣金 {earning} 已发放')
        else:
            log_operation(_get_operator_id(), 'order_unfreeze', 'order', order.id,
                          f'解冻订单 {order.order_no}, 佣金已发放(跳过重复发放)')
    else:
        log_operation(_get_operator_id(), 'order_unfreeze', 'order', order.id,
                      f'解冻订单 {order.order_no}')

    return True, None


def delete_order(order, operator_id=None):
    """
    手动删除订单:
    1) 仅允许删除未付款订单: pending_report / pending_confirm
    2) 若已冻结老板金额，删除前自动解冻退回
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

    # 删除未付款订单前，释放申报冻结金额
    if _quantize_money(order.boss_hold_coin) + _quantize_money(order.boss_hold_gift) > 0:
        _release_order_hold(order, reason='删除订单自动解冻')

    db.session.delete(order)

    log_operation(operator_id or _get_operator_id(), 'order_delete', 'order', order_id, f'删除订单 {order_no}')
    return True, None
