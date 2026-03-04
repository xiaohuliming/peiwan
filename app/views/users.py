from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_, func
from datetime import datetime
from decimal import Decimal

from app.models.user import User
from app.models.order import Order
from app.models.finance import BalanceLog, CommissionLog
from app.models.gift import GiftOrder
from app.models.intimacy import Intimacy
from app.extensions import db
from app.services import balance_service
from app.services.log_service import log_operation
from app.utils.permissions import staff_required, admin_required

users_bp = Blueprint('users', __name__)


@users_bp.route('/create', methods=['POST'])
@login_required
@staff_required
def create():
    """客服/管理员手动新增用户"""
    username = request.form.get('username', '').strip()
    nickname = request.form.get('nickname', '').strip()
    player_nickname = request.form.get('player_nickname', '').strip()
    role = request.form.get('role', 'god')
    kook_id = request.form.get('kook_id', '').strip()
    password = request.form.get('password', '').strip() or '123456789'

    if not username:
        flash('账号不能为空', 'error')
        return redirect(url_for('users.index'))

    # 账号仅支持数字/字母
    if not username.isalnum():
        flash('账号仅支持数字和字母', 'error')
        return redirect(url_for('users.index'))

    if User.query.filter_by(username=username).first():
        flash('该账号已存在', 'error')
        return redirect(url_for('users.index'))

    # 客服只能创建 god / player；管理员可以额外创建 staff
    allowed_roles = ['god', 'player']
    if current_user.is_admin:
        allowed_roles.append('staff')
    if current_user.is_superadmin:
        allowed_roles.extend(['admin', 'superadmin'])

    if role not in allowed_roles:
        flash('无权创建该角色的用户', 'error')
        return redirect(url_for('users.index'))

    # 检查 KOOK ID 是否已被使用
    if kook_id and User.query.filter_by(kook_id=kook_id).first():
        flash('该 KOOK ID 已被其他用户绑定', 'error')
        return redirect(url_for('users.index'))

    # 如果填了 KOOK ID，尝试从 KOOK API 获取用户名和头像
    kook_username = None
    kook_avatar = None
    if kook_id:
        from app.services.kook_service import fetch_kook_user
        kook_username, kook_avatar, _ = fetch_kook_user(kook_id)

    resolved_nickname = nickname or kook_username or username

    new_user = User(
        username=username,
        role=role,
        nickname=resolved_nickname,
        player_nickname=player_nickname if role == 'player' else None,
        kook_id=kook_id or None,
        kook_username=kook_username,
        kook_bound=bool(kook_id),
        avatar=kook_avatar or None,
        status=True,
        register_type='manual',
    )
    new_user.set_password(password)

    db.session.add(new_user)
    db.session.commit()

    log_operation(current_user.id, 'user_create', 'user', new_user.id,
                  f'手动新增用户: {username}, 角色: {new_user.role_name}')

    flash(f'用户 {resolved_nickname} 创建成功', 'success')
    return redirect(url_for('users.index'))


@users_bp.route('/')
@login_required
@staff_required
def index():
    """用户列表"""
    page = request.args.get('page', 1, type=int)
    query = User.query

    # 搜索
    q = request.args.get('q', '').strip()
    if q:
        query = query.filter(or_(
            User.kook_id.ilike(f'%{q}%'),
            User.nickname.ilike(f'%{q}%'),
            User.player_nickname.ilike(f'%{q}%'),
            User.username.ilike(f'%{q}%'),
            User.kook_username.ilike(f'%{q}%'),
        ))

    # 角色筛选
    role_filter = request.args.get('role', '')
    if role_filter:
        query = query.filter(User.role_filter_expr(role_filter))

    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=20)
    pagination_args = request.args.to_dict(flat=True)
    pagination_args.pop('page', None)

    return render_template('users/index.html', users=users, pagination_args=pagination_args)


@users_bp.route('/<int:user_id>')
@login_required
@staff_required
def detail(user_id):
    """用户详情页 — 多标签"""
    user = User.query.get_or_404(user_id)
    tab = request.args.get('tab', 'info')
    page = request.args.get('page', 1, type=int)

    # 日期筛选
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    context = {
        'user': user,
        'tab': tab,
        'date_from': date_from,
        'date_to': date_to,
    }

    if tab == 'balance':
        # 嗯呢币日志
        q = BalanceLog.query.filter_by(user_id=user_id)
        change_type = request.args.get('change_type', '')
        if change_type:
            q = q.filter(BalanceLog.change_type == change_type)
        if date_from:
            q = q.filter(BalanceLog.created_at >= date_from)
        if date_to:
            q = q.filter(BalanceLog.created_at <= date_to + ' 23:59:59')
        context['balance_logs'] = q.order_by(BalanceLog.created_at.desc()).paginate(page=page, per_page=15)

    elif tab == 'commission':
        # 小猪粮日志
        q = CommissionLog.query.filter_by(user_id=user_id)
        change_type = request.args.get('change_type', '')
        if change_type:
            q = q.filter(CommissionLog.change_type == change_type)
        if date_from:
            q = q.filter(CommissionLog.created_at >= date_from)
        if date_to:
            q = q.filter(CommissionLog.created_at <= date_to + ' 23:59:59')
        context['commission_logs'] = q.order_by(CommissionLog.created_at.desc()).paginate(page=page, per_page=15)

    elif tab == 'orders':
        # 订单数据
        q = Order.query.filter(or_(Order.boss_id == user_id, Order.player_id == user_id))
        if date_from:
            q = q.filter(Order.created_at >= date_from)
        if date_to:
            q = q.filter(Order.created_at <= date_to + ' 23:59:59')
        context['orders'] = q.order_by(Order.created_at.desc()).paginate(page=page, per_page=15)

    elif tab == 'intimacy':
        # 亲密度数据
        if user.role == 'god':
            intimacies = Intimacy.query.filter_by(boss_id=user_id).order_by(Intimacy.value.desc()).all()
        else:
            intimacies = Intimacy.query.filter_by(player_id=user_id).order_by(Intimacy.value.desc()).all()
        context['intimacies'] = intimacies

    elif tab == 'summary':
        # 合并数据（用户作为老板视角）：下单给谁 + 送礼给谁（自动排除已退款）
        order_rows = db.session.query(
            Order.player_id,
            func.sum(Order.total_price).label('order_amount')
        ).filter(
            Order.boss_id == user_id,
            Order.status.in_(['pending_pay', 'paid'])
        ).group_by(Order.player_id).all()

        gift_rows = db.session.query(
            GiftOrder.player_id,
            func.sum(GiftOrder.total_price).label('gift_amount')
        ).filter(
            GiftOrder.boss_id == user_id,
            GiftOrder.status == 'paid'
        ).group_by(GiftOrder.player_id).all()

        counterpart_ids = {row[0] for row in order_rows} | {row[0] for row in gift_rows}
        counterpart_users = {}
        if counterpart_ids:
            users = User.query.filter(User.id.in_(counterpart_ids)).all()
            counterpart_users = {u.id: u for u in users}

        merged_map = {}

        for counterpart_id, order_amount in order_rows:
            counterpart = counterpart_users.get(counterpart_id)
            display_name = (counterpart.player_nickname or counterpart.nickname or counterpart.username) if counterpart else '-'
            avatar = counterpart.avatar_url if counterpart else ''
            merged_map[counterpart_id] = {
                'id': counterpart_id,
                'name': display_name,
                'avatar': avatar,
                'order_amount': Decimal(str(order_amount or 0)),
                'gift_amount': Decimal('0'),
            }

        for counterpart_id, gift_amount in gift_rows:
            counterpart = counterpart_users.get(counterpart_id)
            display_name = (counterpart.player_nickname or counterpart.nickname or counterpart.username) if counterpart else '-'
            avatar = counterpart.avatar_url if counterpart else ''
            if counterpart_id not in merged_map:
                merged_map[counterpart_id] = {
                    'id': counterpart_id,
                    'name': display_name,
                    'avatar': avatar,
                    'order_amount': Decimal('0'),
                    'gift_amount': Decimal(str(gift_amount or 0)),
                }
            else:
                merged_map[counterpart_id]['gift_amount'] = Decimal(str(gift_amount or 0))

        summary_items = []
        for item in merged_map.values():
            total_amount = item['order_amount'] + item['gift_amount']
            item['total_amount'] = total_amount
            summary_items.append(item)

        summary_items.sort(key=lambda x: x['total_amount'], reverse=True)
        context['summary_items'] = summary_items

    return render_template('users/detail.html', **context)


@users_bp.route('/<int:user_id>/sync_kook_username', methods=['POST'])
@login_required
@staff_required
def sync_kook_username(user_id):
    """按已绑定 KOOK ID 同步最新 KOOK 名称/头像"""
    user = User.query.get_or_404(user_id)
    ok, changed, error, old_name, new_name = _sync_user_kook_profile(
        user,
        force_nickname=True,
        force_username=True,
    )
    if not ok:
        flash(f'同步失败: {error}', 'error')
        return redirect(request.referrer or url_for('users.index'))

    log_operation(
        current_user.id,
        'user_sync_kook_username',
        'user',
        user.id,
        f'同步KOOK名称: {old_name or "-"} -> {new_name or "-"}',
    )
    db.session.commit()

    flash('已同步最新 KOOK 用户信息' if changed else 'KOOK 用户信息已是最新', 'success')
    return redirect(request.referrer or url_for('users.index'))


@users_bp.route('/sync_kook_usernames', methods=['POST'])
@login_required
@staff_required
def sync_kook_usernames():
    """一键批量同步所有已绑定 KOOK ID 的用户名称/头像，并覆盖客户昵称+用户名。"""
    users = User.query.filter(
        User.kook_id.isnot(None),
        User.kook_id != ''
    ).all()

    if not users:
        flash('没有可同步的用户（未找到已绑定 KOOK ID 的账号）', 'error')
        return redirect(request.referrer or url_for('users.index'))

    success_count = 0
    updated_count = 0
    failed_count = 0
    error_samples = []

    for user in users:
        ok, changed, error, old_name, new_name = _sync_user_kook_profile(
            user,
            force_nickname=True,
            force_username=True,
        )
        if not ok:
            failed_count += 1
            if len(error_samples) < 3:
                error_samples.append(f'{user.nickname or user.username}: {error}')
            continue

        success_count += 1
        if changed:
            updated_count += 1

        log_operation(
            current_user.id,
            'user_sync_kook_username',
            'user',
            user.id,
            f'批量同步KOOK名称: {old_name or "-"} -> {new_name or "-"}',
        )

    db.session.commit()

    summary = (
        f'批量同步完成：共 {len(users)} 个，成功 {success_count} 个，'
        f'有更新 {updated_count} 个，失败 {failed_count} 个'
    )
    flash(summary, 'success' if failed_count == 0 else 'error')
    if error_samples:
        flash('失败示例：' + '；'.join(error_samples), 'error')
    return redirect(request.referrer or url_for('users.index'))


@users_bp.route('/<int:user_id>/adjust_balance', methods=['POST'])
@login_required
@staff_required
def adjust_balance(user_id):
    """手动变账"""
    user = User.query.get_or_404(user_id)
    op_type = request.form.get('op_type')  # recharge / deduct / gift / bean_add / bean_deduct
    amount = request.form.get('amount', '0')
    reason = request.form.get('reason', '').strip()
    target_tab = 'commission' if op_type in ('bean_add', 'bean_deduct') else 'balance'

    try:
        amount = Decimal(amount)
    except Exception:
        flash('无效的金额', 'error')
        return redirect(url_for('users.detail', user_id=user_id, tab=target_tab))

    if op_type == 'recharge':
        success, error = balance_service.manual_recharge(user, amount, reason, current_user.id)
    elif op_type == 'deduct':
        if not current_user.is_admin:
            flash('扣款操作需要管理员权限', 'error')
            return redirect(url_for('users.detail', user_id=user_id, tab='balance'))
        success, error = balance_service.manual_deduct(user, amount, reason, current_user.id)
    elif op_type == 'gift':
        success, error = balance_service.manual_gift_balance(user, amount, reason, current_user.id)
    elif op_type == 'bean_add':
        if not current_user.is_superadmin:
            flash('增加小猪粮仅限高级管理员', 'error')
            return redirect(url_for('users.detail', user_id=user_id, tab=target_tab))
        success, error = balance_service.manual_add_bean(user, amount, reason, current_user.id)
    elif op_type == 'bean_deduct':
        if not current_user.is_superadmin:
            flash('扣减小猪粮仅限高级管理员', 'error')
            return redirect(url_for('users.detail', user_id=user_id, tab=target_tab))
        success, error = balance_service.manual_deduct_bean(user, amount, reason, current_user.id)
    else:
        flash('未知操作类型', 'error')
        return redirect(url_for('users.detail', user_id=user_id, tab=target_tab))

    if success:
        db.session.commit()
        flash(f'变账成功', 'success')
    else:
        flash(error, 'error')

    return redirect(url_for('users.detail', user_id=user_id, tab=target_tab))


@users_bp.route('/<int:user_id>/update_info', methods=['POST'])
@login_required
@staff_required
def update_info(user_id):
    """更新用户信息"""
    user = User.query.get_or_404(user_id)
    action = request.form.get('action')

    if action == 'reset_password':
        if not current_user.is_admin:
            flash('需要管理员权限', 'error')
            return redirect(url_for('users.detail', user_id=user_id))
        user.set_password('123456789')
        log_operation(current_user.id, 'user_password_reset', 'user', user.id, '重置密码为默认')
        db.session.commit()
        flash('密码已重置为 123456789', 'success')

    elif action == 'set_referrer':
        if not current_user.is_admin:
            flash('需要管理员权限', 'error')
            return redirect(url_for('users.detail', user_id=user_id))
        referrer_id = request.form.get('referrer_id', type=int)
        if referrer_id and referrer_id != user.id:
            user.referrer_id = referrer_id
            db.session.commit()
            flash('推荐人已设置', 'success')

    elif action == 'update_experience':
        if not current_user.is_admin:
            flash('需要管理员权限', 'error')
            return redirect(url_for('users.detail', user_id=user_id))
        exp = request.form.get('experience', type=int)
        if exp is not None:
            from app.services.vip_service import check_and_upgrade
            old_exp = user.experience
            user.experience = exp
            upgraded, new_level = check_and_upgrade(user)
            log_operation(current_user.id, 'user_exp_change', 'user', user.id,
                          f'修改经验值 {old_exp} -> {exp}')
            db.session.commit()
            if upgraded and new_level:
                flash(f'经验值已更新，并自动升级到 {new_level.name}', 'success')
            else:
                flash('经验值已更新', 'success')

    elif action in ('toggle_anonymous_all', 'toggle_anonymous_upgrade'):
        new_state = not user.anonymous_broadcast_all
        user.set_anonymous_broadcast_all(new_state)
        log_operation(
            current_user.id,
            'user_toggle_anon_all',
            'user',
            user.id,
            f'{"开启" if new_state else "关闭"}全部匿名播报(充值/消费/送礼/收礼/升级)',
        )
        db.session.commit()
        flash(f'全部匿名播报已{"开启" if new_state else "关闭"}', 'success')

    elif action == 'update_broadcast_channel':
        new_channel = request.form.get('broadcast_channel', '').strip()
        if new_channel != user.broadcast_channel:
            old_channel = user.broadcast_channel
            user.broadcast_channel = new_channel
            log_operation(current_user.id, 'user_update_broadcast_channel', 'user', user.id,
                          f'修改播报频道: {old_channel} -> {new_channel}')
            db.session.commit()
            flash('播报频道已更新', 'success')

    elif action == 'update_nickname':
        nickname = request.form.get('nickname', '').strip()
        player_nickname = request.form.get('player_nickname', '').strip()
        changes = []
        nickname_change_denied = False
        if nickname and nickname != user.nickname:
            if not current_user.is_admin:
                nickname_change_denied = True
            else:
                changes.append(f'昵称: {user.nickname} -> {nickname}')
                user.nickname = nickname
        if player_nickname and player_nickname != user.player_nickname:
            changes.append(f'陪玩昵称: {user.player_nickname} -> {player_nickname}')
            user.player_nickname = player_nickname
        
        if changes:
            log_operation(current_user.id, 'user_update_nickname', 'user', user.id, '; '.join(changes))
            db.session.commit()
            flash('昵称已更新', 'success')
        elif nickname_change_denied:
            flash('客户昵称仅管理员及以上可修改', 'error')

    elif action == 'bind_wechat':
        # 简单模拟绑定/解绑
        if not current_user.is_staff:
             flash('无权限', 'error')
             return redirect(url_for('users.detail', user_id=user_id))
        
        is_bind = request.form.get('is_bind') == 'true'
        if is_bind and not user.wechat_bound:
            user.wechat_bound = True
            user.wechat_openid = f'manual_bind_{user.id}' # 模拟
            log_operation(current_user.id, 'user_bind_wechat', 'user', user.id, '手动绑定微信')
            db.session.commit()
            flash('已标记为绑定微信', 'success')
        elif not is_bind and user.wechat_bound:
            user.wechat_bound = False
            user.wechat_openid = None
            log_operation(current_user.id, 'user_unbind_wechat', 'user', user.id, '手动解绑微信')
            db.session.commit()
            flash('已解除微信绑定', 'success')

    elif action == 'exchange_currency':
        if not current_user.is_admin:
            flash('需要管理员权限', 'error')
            return redirect(url_for('users.detail', user_id=user_id))
        
        # 小猪粮转嗯呢币 (佣金 -> 余额)
        amount = request.form.get('amount', type=float)
        if amount and amount > 0:
            amount_dec = Decimal(str(amount))
            if user.m_bean >= amount_dec:
                user.m_bean -= amount_dec
                user.m_coin += amount_dec
                
                # 记录日志
                from app.models.finance import BalanceLog, CommissionLog
                
                # 扣除 小猪粮
                clog = CommissionLog(
                    user_id=user.id,
                    change_type='exchange_out',
                    amount=-amount_dec,
                    balance_after=user.m_bean,
                    reason='小猪粮转嗯呢币'
                )
                db.session.add(clog)
                
                # 增加 嗯呢币
                blog = BalanceLog(
                    user_id=user.id,
                    change_type='exchange_in',
                    amount=amount_dec,
                    balance_after=user.m_coin + user.m_coin_gift,
                    reason='小猪粮转入'
                )
                db.session.add(blog)
                
                log_operation(current_user.id, 'user_exchange_currency', 'user', user.id, f'小猪粮转嗯呢币: {amount}')
                db.session.commit()
                flash('转换成功', 'success')
            else:
                flash('小猪粮余额不足', 'error')
        else:
            flash('请输入有效金额', 'error')

    return redirect(url_for('users.detail', user_id=user_id))


@users_bp.route('/<int:user_id>/intimacy/<int:intimacy_id>/update', methods=['POST'])
@login_required
@admin_required
def update_intimacy(user_id, intimacy_id):
    """修改亲密度"""
    intimacy = Intimacy.query.get_or_404(intimacy_id)
    new_value = request.form.get('value', type=float)
    if new_value is not None:
        old_value = intimacy.value
        intimacy.value = Decimal(str(new_value))
        log_operation(current_user.id, 'intimacy_update', 'intimacy', intimacy.id,
                      f'修改亲密度: {old_value} -> {new_value}')
        db.session.commit()
        flash('亲密度已更新', 'success')
    return redirect(url_for('users.detail', user_id=user_id, tab='intimacy'))


@users_bp.route('/<int:user_id>/intimacy/<int:intimacy_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_intimacy(user_id, intimacy_id):
    """删除亲密度"""
    intimacy = Intimacy.query.get_or_404(intimacy_id)
    log_operation(current_user.id, 'intimacy_delete', 'intimacy', intimacy.id,
                  f'删除亲密度: {intimacy.boss_id} - {intimacy.player_id}')
    db.session.delete(intimacy)
    db.session.commit()
    flash('亲密度已删除', 'success')
    return redirect(url_for('users.detail', user_id=user_id, tab='intimacy'))


def _sync_user_kook_profile(user, force_nickname=False, force_username=False):
    """按用户已保存的 KOOK ID 拉取并更新 KOOK 名称/头像。"""
    if not user.kook_id:
        return False, False, '该用户未绑定 KOOK ID', '', ''

    old_name = user.kook_username or ''
    old_avatar = user.avatar or ''
    old_nickname = user.nickname or ''
    old_username = user.username or ''

    def _apply_identity_name(identity_name):
        name = (identity_name or '').strip()
        if not name:
            return False, 'KOOK 名称为空'

        if force_username:
            if len(name) > 50:
                return False, f'KOOK 名称过长，无法同步用户名（超过50字符）: {name}'
            conflict = User.query.filter(
                User.username == name,
                User.id != user.id,
            ).first()
            if conflict:
                return False, f'用户名冲突，无法同步为 {name}'
            user.username = name

        if force_nickname:
            user.nickname = name
        elif (not user.nickname) or (old_name and user.nickname == old_name):
            user.nickname = name

        return True, None

    from app.services.kook_service import fetch_kook_user
    kook_username, avatar_url, error = fetch_kook_user(user.kook_id)
    if error:
        # 强制同步场景：接口失败时，用已缓存的 KOOK 名称兜底覆盖客户昵称/用户名
        if (force_nickname or force_username) and user.kook_username:
            ok, fallback_err = _apply_identity_name(user.kook_username)
            if not ok:
                return False, False, fallback_err, old_name, user.kook_username

            changed = (
                (old_nickname != (user.nickname or ''))
                or (old_username != (user.username or ''))
            )
            return True, changed, None, old_name, user.kook_username
        return False, False, error, user.kook_username or '', user.kook_username or ''

    user.kook_username = kook_username
    user.kook_bound = True
    if avatar_url:
        user.avatar = avatar_url

    ok, apply_err = _apply_identity_name(kook_username)
    if not ok:
        return False, False, apply_err, old_name, (kook_username or '')

    changed = (
        (old_name != (kook_username or ''))
        or (bool(avatar_url) and old_avatar != avatar_url)
        or (old_nickname != (user.nickname or ''))
        or (old_username != (user.username or ''))
    )
    return True, changed, None, old_name, (kook_username or '')
