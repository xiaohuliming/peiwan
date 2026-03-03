"""
角色权限体系:
    GOD（老板）    : 下单、查看自己订单、充值、提现、收礼物
    小猪崽（陪玩） : 接单、申报订单、提现、收礼物、查看收益、查看排行
    客服           : 派单、用户管理、订单操作(冻结/解冻)、充值赠金、打卡
    管理员         : 全部客服权限 + 提现审批、数据导出、退款、系统配置、礼物管理、播报管理
    高级管理员     : 全部权限 + 权限分配、账号管理、敏感操作
"""

from functools import wraps
from flask import flash, redirect, url_for, abort
from flask_login import current_user


def role_required(*roles):
    """
    通用角色检查装饰器。
    用法: @role_required('staff', 'admin', 'superadmin')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if current_user.role not in roles:
                flash('无权访问', 'error')
                return redirect(url_for('dashboard.index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def staff_required(f):
    """客服及以上 (客服/管理员/高级管理员)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_staff:
            flash('需要客服及以上权限', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """管理员及以上 (管理员/高级管理员)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_admin:
            flash('需要管理员及以上权限', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def superadmin_required(f):
    """仅高级管理员"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_superadmin:
            flash('需要高级管理员权限', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def player_required(f):
    """仅陪玩"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_player:
            flash('仅陪玩可访问', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


def god_required(f):
    """仅老板"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_god:
            flash('仅老板可访问', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function


# ===== 权限检查辅助函数 (用于模板和视图内部判断) =====

def can_dispatch_order(user):
    """派单权限: 客服+"""
    return user.is_staff


def can_freeze_order(user):
    """冻结/解冻权限: 客服+"""
    return user.is_staff


def can_refund_order(user):
    """退款权限: 管理员+"""
    return user.is_admin


def can_delete_order(user):
    """删除订单权限: 客服+"""
    return user.is_staff


def can_approve_withdraw(user):
    """提现审批权限: 管理员+"""
    return user.is_admin


def can_manage_users(user):
    """用户管理权限: 客服+"""
    return user.is_staff


def can_adjust_balance(user, adjust_type='recharge'):
    """
    余额变账权限:
    - 充值/赠金: 客服+
    - 扣款: 管理员+
    """
    if adjust_type == 'deduct':
        return user.is_admin
    return user.is_staff


def can_manage_accounts(user):
    """账号管理(改角色/删除): 高级管理员"""
    return user.is_superadmin


def can_export_data(user):
    """数据导出: 管理员+"""
    return user.is_admin


def can_view_stats(user):
    """查看统计: 客服+"""
    return user.is_staff


def can_manage_system(user):
    """系统配置: 管理员+"""
    return user.is_admin
