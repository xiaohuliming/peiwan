from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from app.extensions import db
from app.models.gift import Gift, GiftOrder
from app.models.user import User
from app.models.finance import BalanceLog, CommissionLog
from app.services.log_service import log_operation


def _quantize_money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def send_gift(boss, player, gift, quantity, staff=None):
    """
    赠送礼物:
    1. 扣老板嗯呢币余额
    2. 发放陪玩佣金(小猪粮)
    3. 冠名礼物自动冻结
    """
    quantity = int(quantity)
    if quantity <= 0:
        return None, '数量必须大于0'

    unit_price = Decimal(str(gift.price))
    total_price = unit_price * quantity

    # 验证余额
    total_available = boss.m_coin + boss.m_coin_gift
    if total_available < total_price:
        return None, '老板余额不足'

    # 计算分成 (默认80%, 陪玩自定义优先)
    commission_rate = Decimal(str(player.commission_rate)) if player.commission_rate is not None else Decimal('80')
    player_earning = (total_price * commission_rate / Decimal('100')).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    shop_earning = total_price - player_earning

    # 创建礼物订单
    gift_order = GiftOrder(
        boss_id=boss.id,
        player_id=player.id,
        staff_id=staff.id if staff else None,
        gift_id=gift.id,
        quantity=quantity,
        unit_price=unit_price,
        total_price=total_price,
        commission_rate=commission_rate,
        player_earning=player_earning,
        shop_earning=shop_earning,
        status='paid',
        freeze_status='frozen' if gift.gift_type == 'crown' else 'normal',
    )
    db.session.add(gift_order)
    db.session.flush()

    # 扣老板余额 (优先扣 m_coin)
    amount = total_price
    if boss.m_coin >= amount:
        coin_deducted = amount
        gift_deducted = Decimal('0')
        boss.m_coin -= amount
    else:
        coin_deducted = boss.m_coin
        gift_deducted = amount - boss.m_coin
        boss.m_coin = Decimal('0')
        boss.m_coin_gift -= gift_deducted

    # 记录嗯呢币/赠金拆分（用于原路退款）
    gift_order.boss_paid_coin = coin_deducted
    gift_order.boss_paid_gift = gift_deducted

    receiver_name = player.player_nickname or player.nickname or player.username

    # 记录消费日志
    balance_log = BalanceLog(
        user_id=boss.id,
        change_type='gift_send',
        amount=-total_price,
        balance_after=boss.m_coin + boss.m_coin_gift,
        reason=f'赠送 {gift.name} x{quantity} 给 {receiver_name}'
    )
    db.session.add(balance_log)

    # m_coin消费增加经验（支持身份标签经验倍率）
    from app.services.vip_service import apply_consume_experience, check_and_upgrade
    apply_consume_experience(boss, coin_deducted)

    # 检查VIP升级
    check_and_upgrade(boss)

    # 发放陪玩佣金
    if gift.gift_type == 'crown':
        # 冠名礼物: 佣金冻结
        player.m_bean_frozen += player_earning
    else:
        # 标准礼物: 直接到账
        player.m_bean += player_earning
        commission_log = CommissionLog(
            user_id=player.id,
            change_type='gift_income',
            amount=player_earning,
            balance_after=player.m_bean,
            reason=f'收到 {boss.nickname or boss.username} 的 {gift.name} x{quantity}'
        )
        db.session.add(commission_log)

    # 增加亲密度 (基于礼物总价, 1嗯呢币 = 1亲密度)
    from app.services.intimacy_service import update_intimacy
    update_intimacy(boss.id, player.id, total_price)

    # KOOK 私信通知（老板消费）
    try:
        from app.services.kook_service import push_boss_consume_notice
        operator = staff.staff_display_name if staff else ''
        push_boss_consume_notice(
            boss,
            total_price,
            reason=balance_log.reason,
            operator=operator,
        )
    except Exception:
        pass

    # KOOK 标签自动授予（礼物配置了标签时）
    try:
        from app.services.kook_service import grant_kook_role, _async_send

        class _UserLike:
            def __init__(self, uid, kook_id):
                self.id = uid
                self.kook_id = kook_id

        if gift.sender_kook_role_id and boss.kook_id:
            _async_send(grant_kook_role, _UserLike(boss.id, boss.kook_id), gift.sender_kook_role_id)
        if gift.receiver_kook_role_id and player.kook_id:
            _async_send(grant_kook_role, _UserLike(player.id, player.kook_id), gift.receiver_kook_role_id)
    except Exception:
        pass

    # 客服提成仅用于平台绩效统计，不写入客服余额。

    # 操作日志
    if staff:
        log_operation(
            operator_id=staff.id,
            action_type='gift_send',
            target_type='gift_order',
            target_id=gift_order.id,
            detail=f'派发礼物: {gift.name} x{quantity}, 老板: {boss.nickname or boss.username}, 收礼人: {receiver_name}'
        )

    return gift_order, None


def freeze_gift_order(gift_order, operator_id=None):
    """冻结礼物订单"""
    if gift_order.freeze_status == 'frozen':
        return False, '已冻结'
    gift_order.freeze_status = 'frozen'
    if operator_id:
        log_operation(operator_id, 'gift_freeze', 'gift_order', gift_order.id, '冻结礼物订单')
    return True, None


def unfreeze_gift_order(gift_order, operator_id=None):
    """解冻礼物订单 -- 冠名礼物解冻后佣金到账"""
    if gift_order.freeze_status != 'frozen':
        return False, '未冻结'

    gift_order.freeze_status = 'normal'

    # 如果是冠名礼物且佣金还在冻结中, 将冻结佣金转为可用
    player = gift_order.player
    earning = gift_order.player_earning
    if player.m_bean_frozen >= earning:
        player.m_bean_frozen -= earning
        player.m_bean += earning
        commission_log = CommissionLog(
            user_id=player.id,
            change_type='gift_income',
            amount=earning,
            balance_after=player.m_bean,
            reason=f'礼物订单 #{gift_order.id} 解冻到账'
        )
        db.session.add(commission_log)

    if operator_id:
        log_operation(operator_id, 'gift_unfreeze', 'gift_order', gift_order.id, '解冻礼物订单')
    return True, None


def refund_gift_order(gift_order, operator_id=None):
    """礼物退款"""
    if gift_order.status == 'refunded':
        return False, '已退款'

    boss = gift_order.boss
    player = gift_order.player
    total_price = gift_order.total_price
    player_earning = gift_order.player_earning
    is_crown = bool(gift_order.gift and gift_order.gift.gift_type == 'crown')

    # 先校验可扣佣金，避免出现"老板已退款但陪玩仅被清零"的账务不一致
    available_frozen = _quantize_money(player.m_bean_frozen)
    available_bean = _quantize_money(player.m_bean)
    if is_crown:
        total_available = available_frozen + available_bean
        if total_available < player_earning:
            shortfall = (player_earning - total_available).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return False, f'退款失败：冠名礼物可扣收益不足，差额 {shortfall} 小猪粮，请先补足后再退款'
    else:
        if available_bean < player_earning:
            shortfall = (player_earning - available_bean).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return False, f'退款失败：陪玩佣金不足，差额 {shortfall} 小猪粮，请先补足后再退款'

    # 退还老板余额（原路退回）
    coin_back = _quantize_money(gift_order.boss_paid_coin)
    gift_back = _quantize_money(gift_order.boss_paid_gift)
    # 兼容历史数据：如果没有记录拆分，全部退到 m_coin
    if coin_back + gift_back <= 0:
        coin_back = total_price
        gift_back = Decimal('0')
    boss.m_coin += coin_back
    boss.m_coin_gift += gift_back
    balance_log = BalanceLog(
        user_id=boss.id,
        change_type='refund',
        amount=total_price,
        balance_after=boss.m_coin + boss.m_coin_gift,
        reason=f'礼物订单 #{gift_order.id} 退款 (币:{coin_back}, 赠:{gift_back})'
    )
    db.session.add(balance_log)

    # 扣回陪玩佣金
    # 冠名礼物: 优先扣冻结余额，不足再扣可用余额
    if is_crown:
        frozen_deduct = min(_quantize_money(player.m_bean_frozen), player_earning)
        player.m_bean_frozen -= frozen_deduct
        remaining = player_earning - frozen_deduct
        if remaining > 0:
            player.m_bean -= remaining
    else:
        # 标准礼物: 仅扣可用余额
        player.m_bean -= player_earning

    commission_log = CommissionLog(
        user_id=player.id,
        change_type='refund_deduct',
        amount=-player_earning,
        balance_after=player.m_bean,
        reason=f'礼物订单 #{gift_order.id} 退款扣回'
    )
    db.session.add(commission_log)

    gift_order.status = 'refunded'
    gift_order.freeze_status = 'normal'
    gift_order.refund_time = datetime.utcnow()

    # 退款扣除亲密度
    from app.services.intimacy_service import update_intimacy
    update_intimacy(boss.id, player.id, -total_price)

    if operator_id:
        gift_name = gift_order.gift.name if gift_order.gift else f'礼物#{gift_order.gift_id}'
        detail = f'礼物退款: {gift_name} x{gift_order.quantity}'
        log_operation(operator_id, 'gift_refund', 'gift_order', gift_order.id,
                      detail)
    return True, None
