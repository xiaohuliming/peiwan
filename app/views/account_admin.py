import json
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import User
from app.models.order import Order
from app.models.finance import BalanceLog, CommissionLog, WithdrawRequest
from app.models.intimacy import Intimacy
from app.models.gift import GiftOrder
from app.models.vip import UpgradeRecord
from app.models.operation_log import OperationLog
from app.models.clock import ClockRecord
from app.models.lottery import Lottery
from app.utils.permissions import admin_required, superadmin_required
from app.services.log_service import log_operation

account_admin_bp = Blueprint('account_admin', __name__, template_folder='../templates')


@account_admin_bp.route('/')
@login_required
@admin_required
def index():
    page = request.args.get('page', 1, type=int)
    q = request.args.get('q', '').strip()
    role_filter = request.args.get('role', '')

    query = User.query
    if q:
        query = query.filter(
            db.or_(
                User.username.contains(q),
                User.nickname.contains(q),
                User.kook_username.contains(q),
                User.kook_id.contains(q),
            )
        )
    if role_filter:
        query = query.filter(User.role_filter_expr(role_filter))

    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('admin/accounts.html', users=users, q=q, role_filter=role_filter)


@account_admin_bp.route('/<int:user_id>/change_role', methods=['POST'])
@login_required
@admin_required
def change_role(user_id):
    user = User.query.get_or_404(user_id)
    new_role = request.form.get('role', '')

    valid_roles = ['god', 'player', 'staff', 'admin', 'superadmin']
    if new_role not in valid_roles:
        flash('无效角色', 'error')
        return redirect(url_for('account_admin.index'))

    # 只有高级管理员可以设管理员/高级管理员
    if new_role in ('admin', 'superadmin') and not current_user.is_superadmin:
        flash('只有高级管理员可以提升为管理员', 'error')
        return redirect(url_for('account_admin.index'))

    # 不能修改自己
    if user.id == current_user.id:
        flash('不能修改自己的角色', 'error')
        return redirect(url_for('account_admin.index'))

    old_role = user.role
    user.role = new_role
    db.session.commit()

    log_operation(current_user.id, 'user_role_change', 'user', user.id,
                  f'角色变更: {old_role} → {new_role}, 用户: {user.nickname or user.username}')
    db.session.commit()

    flash(f'已将 {user.nickname or user.username} 角色更改为 {new_role}', 'success')
    return redirect(url_for('account_admin.index'))


@account_admin_bp.route('/<int:user_id>/reset_password', methods=['POST'])
@login_required
@admin_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    default_password = '123456789'
    user.set_password(default_password)
    db.session.commit()

    log_operation(current_user.id, 'user_reset_password', 'user', user.id,
                  f'重置密码: {user.nickname or user.username}')
    db.session.commit()

    flash(f'已重置 {user.nickname or user.username} 密码为 {default_password}', 'success')
    return redirect(url_for('account_admin.index'))


@account_admin_bp.route('/<int:user_id>/rename', methods=['POST'])
@login_required
@admin_required
def rename(user_id):
    user = User.query.get_or_404(user_id)
    new_nickname = request.form.get('nickname', '').strip()
    if not new_nickname:
        flash('昵称不能为空', 'error')
        return redirect(url_for('account_admin.index'))

    old_name = user.nickname
    user.nickname = new_nickname
    db.session.commit()

    log_operation(current_user.id, 'user_rename', 'user', user.id,
                  f'修改昵称: {old_name} → {new_nickname}')
    db.session.commit()

    flash('昵称已修改', 'success')
    return redirect(url_for('account_admin.index'))


@account_admin_bp.route('/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('不能删除自己的账户', 'error')
        return redirect(url_for('account_admin.index'))

    # 不允许删除高级管理员
    if user.is_superadmin:
        flash('不能删除高级管理员账户', 'error')
        return redirect(url_for('account_admin.index'))

    name = user.nickname or user.username
    uid = user.id

    try:
        # 1. 删除用户直接关联的记录 (user_id NOT NULL)
        BalanceLog.query.filter_by(user_id=uid).delete()
        CommissionLog.query.filter_by(user_id=uid).delete()
        WithdrawRequest.query.filter_by(user_id=uid).delete()
        ClockRecord.query.filter_by(user_id=uid).delete()
        UpgradeRecord.query.filter_by(user_id=uid).delete()
        OperationLog.query.filter_by(operator_id=uid).delete()

        # 2. 删除亲密度记录 (boss 或 player 关联)
        Intimacy.query.filter((Intimacy.boss_id == uid) | (Intimacy.player_id == uid)).delete(synchronize_session=False)

        # 3. 删除订单 (boss 或 player 关联) 及关联的佣金日志
        orders = Order.query.filter((Order.boss_id == uid) | (Order.player_id == uid)).all()
        for order in orders:
            CommissionLog.query.filter_by(order_id=order.id).delete()
        Order.query.filter((Order.boss_id == uid) | (Order.player_id == uid)).delete(synchronize_session=False)
        # 清空 staff_id 引用
        Order.query.filter_by(staff_id=uid).update({'staff_id': None})

        # 4. 删除礼物订单
        GiftOrder.query.filter((GiftOrder.boss_id == uid) | (GiftOrder.player_id == uid)).delete(synchronize_session=False)
        GiftOrder.query.filter_by(staff_id=uid).update({'staff_id': None})

        # 5. 清空 nullable FK 引用
        BalanceLog.query.filter_by(operator_id=uid).update({'operator_id': None})
        WithdrawRequest.query.filter_by(auditor_id=uid).update({'auditor_id': None})
        UpgradeRecord.query.filter_by(granted_by=uid).update({'granted_by': None})

        # 6. 清空 User 自引用
        User.query.filter_by(referrer_id=uid).update({'referrer_id': None})

        # 6.1 抽奖创建人是 NOT NULL，删除用户前需转移归属
        # 这里转给当前操作管理员，避免 created_by 置空触发 IntegrityError
        Lottery.query.filter_by(created_by=uid).update({'created_by': current_user.id})

        # 7. 记录日志后删除用户
        log_operation(current_user.id, 'user_delete', 'user', uid,
                      f'删除用户: {name} (含关联数据清零)')

        db.session.delete(user)
        db.session.commit()

        flash(f'用户 {name} 及其关联数据已删除', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'删除失败: {str(e)}', 'error')

    return redirect(url_for('account_admin.index'))


@account_admin_bp.route('/<int:user_id>/tags', methods=['POST'])
@login_required
@admin_required
def manage_tags(user_id):
    """批量设置用户标签 — 用提交的标签列表完整替换"""
    user = User.query.get_or_404(user_id)

    old_tags = user.tag_list
    # 收集所有勾选的标签 (getlist 支持多个同名字段)
    new_tags = request.form.getlist('tags')
    # 去重、去空、保持顺序
    seen = set()
    clean_tags = []
    for t in new_tags:
        t = t.strip()
        if t and t not in seen:
            clean_tags.append(t)
            seen.add(t)

    user.tag_list = clean_tags
    db.session.commit()

    added = [t for t in clean_tags if t not in old_tags]
    removed = [t for t in old_tags if t not in clean_tags]
    changes = []
    if added:
        changes.append(f'添加: {", ".join(added)}')
    if removed:
        changes.append(f'移除: {", ".join(removed)}')

    if changes:
        log_operation(current_user.id, 'user_tags_update', 'user', user.id,
                      f'更新身份标签: {"; ".join(changes)}, 用户: {user.nickname or user.username}')
        db.session.commit()
        flash(f'身份标签已更新', 'success')
    else:
        flash('身份标签无变化', 'info')

    return redirect(request.referrer or url_for('account_admin.index'))
