"""
VIP自动升级服务
"""
from app.extensions import db
from app.models.user import User
from app.models.vip import VipLevel, UpgradeRecord


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
    levels = levels or get_vip_levels()
    if not levels:
        return False, None

    # 找到用户应该对应的最高等级（按经验门槛，不依赖 sort_order 配置顺序）
    target_level = _pick_target_level(levels, user.experience)

    # 如果已经是当前等级, 不需要升级
    if user.vip_level == target_level.name:
        return False, None

    # 检查是否是升级（不做降级）
    level_by_name = {lv.name: lv for lv in levels}
    current_level = level_by_name.get(user.vip_level)
    current_rank = _level_rank(current_level) if current_level else (0, -1)
    target_rank = _level_rank(target_level)
    if target_rank <= current_rank:
        return False, None

    # 执行升级
    old_level = user.vip_level
    user.vip_level = target_level.name

    # 记录升级
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
        push_upgrade_broadcast(user, old_level, target_level.name)
    except Exception:
        pass  # 推送失败不影响升级流程

    return True, target_level


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
