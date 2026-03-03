from decimal import Decimal
from app.extensions import db
from app.models.user import User
from app.models.finance import BalanceLog, CommissionLog
from app.services.log_service import log_operation


def _operator_name(operator_id):
    operator = db.session.get(User, operator_id) if operator_id else None
    if not operator:
        return ''
    return operator.staff_display_name


def manual_recharge(user, amount, reason, operator_id):
    """手动充值 (嗯呢币)"""
    amount = Decimal(str(amount))
    if amount <= 0:
        return False, '金额必须大于0'

    user.m_coin += amount
    log = BalanceLog(
        user_id=user.id,
        change_type='recharge',
        amount=amount,
        balance_after=user.m_coin + user.m_coin_gift,
        reason=reason or '管理员手动充值',
        operator_id=operator_id,
    )
    db.session.add(log)
    log_operation(operator_id, 'balance_recharge', 'user', user.id,
                  f'手动充值 {amount} 嗯呢币, 理由: {reason}')

    # KOOK 充值播报
    try:
        from app.services.kook_service import push_recharge_broadcast, push_boss_recharge_notice
        push_recharge_broadcast(user, amount)
        push_boss_recharge_notice(
            user,
            amount,
            reason=log.reason,
            operator=_operator_name(operator_id),
        )
    except Exception:
        pass  # 推送失败不影响充值流程

    return True, None


def manual_deduct(user, amount, reason, operator_id):
    """手动扣款 (嗯呢币) — 仅管理员+"""
    amount = Decimal(str(amount))
    if amount <= 0:
        return False, '金额必须大于0'

    total = user.m_coin + user.m_coin_gift
    if total < amount:
        return False, '余额不足'

    # 优先扣 m_coin
    if user.m_coin >= amount:
        user.m_coin -= amount
    else:
        remainder = amount - user.m_coin
        user.m_coin = Decimal('0')
        user.m_coin_gift -= remainder

    log = BalanceLog(
        user_id=user.id,
        change_type='admin_adjust',
        amount=-amount,
        balance_after=user.m_coin + user.m_coin_gift,
        reason=reason or '管理员手动扣款',
        operator_id=operator_id,
    )
    db.session.add(log)
    log_operation(operator_id, 'balance_deduct', 'user', user.id,
                  f'手动扣款 {amount} 嗯呢币, 理由: {reason}')

    # KOOK 私信通知（老板消费）
    try:
        from app.services.kook_service import push_boss_consume_notice
        push_boss_consume_notice(
            user,
            amount,
            reason=log.reason,
            operator=_operator_name(operator_id),
        )
    except Exception:
        pass

    return True, None


def manual_gift_balance(user, amount, reason, operator_id):
    """赠金 (增加 m_coin_gift)"""
    amount = Decimal(str(amount))
    if amount <= 0:
        return False, '金额必须大于0'

    user.m_coin_gift += amount
    log = BalanceLog(
        user_id=user.id,
        change_type='gift_send',
        amount=amount,
        balance_after=user.m_coin + user.m_coin_gift,
        reason=reason or '管理员赠金',
        operator_id=operator_id,
    )
    db.session.add(log)
    log_operation(operator_id, 'balance_gift', 'user', user.id,
                  f'赠金 {amount} 嗯呢币, 理由: {reason}')

    # KOOK 私信通知（老板充值）
    try:
        from app.services.kook_service import push_boss_recharge_notice
        push_boss_recharge_notice(
            user,
            amount,
            reason=log.reason,
            operator=_operator_name(operator_id),
        )
    except Exception:
        pass

    return True, None


def manual_add_bean(user, amount, reason, operator_id):
    """手动增加小猪粮 — 仅高级管理员"""
    amount = Decimal(str(amount))
    if amount <= 0:
        return False, '金额必须大于0'

    user.m_bean += amount
    log = CommissionLog(
        user_id=user.id,
        change_type='admin_adjust',
        amount=amount,
        balance_after=user.m_bean,
        reason=reason or '高级管理员手动增加小猪粮',
    )
    db.session.add(log)
    log_operation(operator_id, 'bean_add', 'user', user.id,
                  f'手动增加 {amount} 小猪粮, 理由: {reason}')
    return True, None


def manual_deduct_bean(user, amount, reason, operator_id):
    """手动扣减小猪粮 — 仅高级管理员"""
    amount = Decimal(str(amount))
    if amount <= 0:
        return False, '金额必须大于0'

    if user.m_bean < amount:
        return False, '小猪粮余额不足'

    user.m_bean -= amount
    log = CommissionLog(
        user_id=user.id,
        change_type='admin_adjust',
        amount=-amount,
        balance_after=user.m_bean,
        reason=reason or '高级管理员手动扣减小猪粮',
    )
    db.session.add(log)
    log_operation(operator_id, 'bean_deduct', 'user', user.id,
                  f'手动扣减 {amount} 小猪粮, 理由: {reason}')
    return True, None
