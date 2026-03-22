"""
VIP自动升级服务
"""
import logging
from decimal import Decimal

from app.extensions import db
from app.models.user import User
from app.models.vip import VipLevel, UpgradeRecord
from app.models.identity_tag import IdentityTag

logger = logging.getLogger(__name__)


def get_vip_levels():
    """获取所有VIP等级(按sort_order升序)"""
    return VipLevel.query.order_by(VipLevel.sort_order).all()


def _level_rank(level):
    """
    等级排序键:
    先看经验门槛，再看 sort_order（用于同门槛时兜底）。
    """
    return (int(level.min_experience or 0), int(level.sort_order or 0))


def _pick_target_level(levels, experience):
    """按经验值挑选应达到的最高等级"""
    exp = int(experience or 0)
    eligible = [lv for lv in levels if exp >= int(lv.min_experience or 0)]
    if eligible:
        return max(eligible, key=_level_rank)
    # 经验低于所有门槛时，回退到最低等级
    return min(levels, key=_level_rank)


def check_and_upgrade(user, levels=None):
    """
    检查用户经验值, 判断是否需要升级
    返回: (upgraded: bool, new_level: VipLevel or None)
    """
    changed, target_level, direction = sync_vip_level_by_experience(
        user,
        levels=levels,
        allow_downgrade=False,
    )
    if changed and direction == 'upgrade':
        return True, target_level
    return False, None


def sync_vip_level_by_experience(user, levels=None, allow_downgrade=True):
    """
    按经验值同步用户 VIP 等级（可升可降）。
    返回: (changed: bool, target_level: VipLevel or None, direction: 'upgrade'|'downgrade'|'same')
    """
    levels = levels or get_vip_levels()
    if not levels:
        return False, None, 'same'

    # 找到用户应该对应的最高等级（按经验门槛，不依赖 sort_order 配置顺序）
    target_level = _pick_target_level(levels, user.experience)

    # 如果已经是当前等级, 不需要变更
    if user.vip_level == target_level.name:
        return False, None, 'same'

    # 计算方向
    level_by_name = {lv.name: lv for lv in levels}
    current_level = level_by_name.get(user.vip_level)
    current_rank = _level_rank(current_level) if current_level else (0, -1)
    target_rank = _level_rank(target_level)
    direction = 'upgrade' if target_rank > current_rank else 'downgrade'
    if direction == 'downgrade' and not allow_downgrade:
        return False, None, 'same'

    # 执行等级同步
    old_level = user.vip_level
    user.vip_level = target_level.name

    # 升级才写升级记录并发升级播报；降级不走升级奖励流程
    if direction == 'upgrade':
        record = UpgradeRecord(
            user_id=user.id,
            from_level=old_level,
            to_level=target_level.name,
            benefit_status='pending',
        )
        db.session.add(record)

        # KOOK 升级播报
        try:
            from app.services.kook_service import push_upgrade_broadcast
            queued = push_upgrade_broadcast(user, old_level, target_level.name)
            if queued > 0:
                logger.info('[VIP] 升级播报已触发 user=%s %s -> %s configs=%s', user.id, old_level, target_level.name, queued)
            else:
                logger.warning('[VIP] 升级完成但未命中可用播报配置 user=%s %s -> %s', user.id, old_level, target_level.name)
        except Exception as e:
            logger.warning('[VIP] 升级播报异常 user=%s %s -> %s: %s', user.id, old_level, target_level.name, e)

        # KOOK 角色自动授予
        try:
            kook_role = getattr(target_level, 'kook_role_id', None)
            if kook_role:
                from app.services.kook_service import grant_kook_role, _async_send
                _async_send(grant_kook_role, user, kook_role)
                logger.info('[VIP] 升级标签授予已触发 user=%s role=%s level=%s', user.id, kook_role, target_level.name)
        except Exception as e:
            logger.warning('[VIP] 升级标签授予异常 user=%s: %s', user.id, e)

    return True, target_level, direction


def _get_active_consume_exp_rule(user):
    """
    获取用户当前生效的消费经验加成规则。
    规则生效条件：
    1) 用户拥有该身份标签
    2) 规则启用，倍率 > 1
    3) 配置了经验阈值，且当前经验 < 阈值
    冲突处理：取倍率最高的一条。
    """
    tags = set(user.tag_list or [])
    if not tags:
        return None

    rules = (
        IdentityTag.query
        .filter(
            IdentityTag.status == True,
            IdentityTag.name.in_(list(tags)),
            IdentityTag.exp_multiplier > Decimal('1.00'),
            IdentityTag.exp_bonus_until.isnot(None),
        )
        .all()
    )
    if not rules:
        return None

    current_exp = int(user.experience or 0)
    valid = []
    for rule in rules:
        threshold = int(rule.exp_bonus_until or 0)
        if threshold > 0 and current_exp < threshold:
            valid.append(rule)
    if not valid:
        return None

    return max(valid, key=lambda r: Decimal(str(r.exp_multiplier or 1)))


def apply_consume_experience(user, coin_amount):
    """
    按身份标签规则计算并增加消费经验。
    返回: (gain_exp, multiplier, rule_name)
    """
    base_exp = int(Decimal(str(coin_amount or 0)))
    if base_exp <= 0:
        return 0, Decimal('1.00'), None

    rule = _get_active_consume_exp_rule(user)
    multiplier = Decimal(str(rule.exp_multiplier if rule else 1))
    gain_exp = int(Decimal(base_exp) * multiplier)

    user.experience = int(user.experience or 0) + gain_exp
    return gain_exp, multiplier, (rule.name if rule else None)


def batch_check_upgrades():
    """
    批量检查所有老板身份用户的VIP升级 (定时任务调用)
    返回升级数量
    """
    levels = get_vip_levels()
    if not levels:
        return 0

    gods = User.query.filter(User.role_filter_expr('god')).all()
    count = 0
    for user in gods:
        upgraded, _ = check_and_upgrade(user, levels=levels)
        if upgraded:
            count += 1
    if count > 0:
        db.session.commit()
    return count
