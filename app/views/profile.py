import secrets
import time
from flask import Blueprint, render_template, request, flash, redirect, url_for, session, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from app.models.order import Order
from app.models.finance import CommissionLog, BalanceLog
from app.extensions import db
from app.services import upload_service

profile_bp = Blueprint('profile', __name__)
_EXCLUDED_BEAN_TYPES = ('staff_commission', 'staff_refund_deduct')

# 修改密码验证码相关
_PWD_CODE_SESSION_KEY = 'pwd_change_code'
_PWD_CODE_EXPIRES_KEY = 'pwd_change_code_expires'
_PWD_CODE_USER_KEY = 'pwd_change_code_user'
_PWD_CODE_LAST_SEND_KEY = 'pwd_change_code_last_send'
_PWD_CODE_TTL = 300  # 5 分钟有效
_PWD_CODE_RESEND_INTERVAL = 60  # 60 秒内不能重复发送

@profile_bp.route('/')
@login_required
def index():
    current_tab = request.args.get('tab', 'info')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    page = request.args.get('page', 1, type=int)
    balance_page = request.args.get('balance_page', 1, type=int)
    bean_page = request.args.get('bean_page', 1, type=int)

    orders = None
    earnings = None
    balance_logs = None
    bean_logs = None

    if current_tab == 'orders':
        # 根据主角色查询订单，避免默认身份标签导致错位
        if current_user.role == 'god':
            query = Order.query.filter(Order.boss_id == current_user.id)
        elif current_user.role == 'player':
            query = Order.query.filter(Order.player_id == current_user.id)
        elif current_user.role in ('staff', 'admin', 'superadmin'):
            query = Order.query.filter(Order.staff_id == current_user.id)
        else:
            query = Order.query.filter(
                (Order.boss_id == current_user.id) | (Order.player_id == current_user.id)
            )

        # 日期筛选
        if start_date:
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(Order.created_at >= start_dt)
            except ValueError:
                pass
        if end_date:
            try:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                # 包含结束日期当天
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
                query = query.filter(Order.created_at <= end_dt)
            except ValueError:
                pass

        orders = query.order_by(Order.created_at.desc()).paginate(page=page, per_page=10, error_out=False)

    elif current_tab == 'earnings' and current_user.is_player:
        query = CommissionLog.query.filter(CommissionLog.user_id == current_user.id)
        query = query.filter(~CommissionLog.change_type.in_(_EXCLUDED_BEAN_TYPES))

        if start_date:
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(CommissionLog.created_at >= start_dt)
            except ValueError:
                pass
        if end_date:
            try:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                end_dt = end_dt.replace(hour=23, minute=59, second=59)
                query = query.filter(CommissionLog.created_at <= end_dt)
            except ValueError:
                pass

        earnings = query.order_by(CommissionLog.created_at.desc()).paginate(page=page, per_page=10, error_out=False)

    elif current_tab == 'wallet':
        balance_query = BalanceLog.query.filter(BalanceLog.user_id == current_user.id)
        bean_query = CommissionLog.query.filter(CommissionLog.user_id == current_user.id)
        bean_query = bean_query.filter(~CommissionLog.change_type.in_(_EXCLUDED_BEAN_TYPES))

        if start_date:
            try:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                balance_query = balance_query.filter(BalanceLog.created_at >= start_dt)
                bean_query = bean_query.filter(CommissionLog.created_at >= start_dt)
            except ValueError:
                pass
        if end_date:
            try:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
                balance_query = balance_query.filter(BalanceLog.created_at <= end_dt)
                bean_query = bean_query.filter(CommissionLog.created_at <= end_dt)
            except ValueError:
                pass

        balance_logs = balance_query.order_by(BalanceLog.created_at.desc()).paginate(
            page=balance_page, per_page=10, error_out=False
        )
        bean_logs = bean_query.order_by(CommissionLog.created_at.desc()).paginate(
            page=bean_page, per_page=10, error_out=False
        )

    return render_template('profile/index.html',
                           current_tab=current_tab,
                           orders=orders,
                           earnings=earnings,
                           balance_logs=balance_logs,
                           bean_logs=bean_logs,
                           start_date=start_date,
                           end_date=end_date)

@profile_bp.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    current_user.anonymous_recharge = request.form.get('anonymous_recharge') == 'on'
    current_user.anonymous_consume = request.form.get('anonymous_consume') == 'on'
    current_user.anonymous_gift_send = request.form.get('anonymous_gift_send') == 'on'
    current_user.anonymous_gift_recv = request.form.get('anonymous_gift_recv') == 'on'
    current_user.anonymous_upgrade = request.form.get('anonymous_upgrade') == 'on'
    current_user.anonymous_ranking = request.form.get('anonymous_ranking') == 'on'

    try:
        db.session.commit()
        flash('设置已更新', 'success')
    except Exception as e:
        db.session.rollback()
        flash('设置更新失败', 'error')

    return redirect(url_for('profile.index', tab='info'))


@profile_bp.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    """编辑个人资料（昵称/陪玩昵称）"""
    nickname = request.form.get('nickname', '').strip()
    player_nickname = request.form.get('player_nickname', '').strip()

    if not nickname:
        flash('客户昵称不能为空', 'error')
        return redirect(url_for('profile.index', tab='info'))

    current_user.nickname = nickname
    if current_user.role == 'player':
        current_user.player_nickname = player_nickname or current_user.player_nickname or nickname

    try:
        db.session.commit()
        flash('资料已更新', 'success')
    except Exception:
        db.session.rollback()
        flash('资料更新失败', 'error')

    return redirect(url_for('profile.index', tab='info'))


@profile_bp.route('/update_avatar', methods=['POST'])
@login_required
def update_avatar():
    """修改个人头像"""
    file = request.files.get('avatar')
    if not file or not file.filename:
        flash('请选择头像图片', 'error')
        return redirect(url_for('profile.index', tab='info'))

    path, error = upload_service.save_file(file, 'avatars')
    if error:
        flash(f'头像上传失败: {error}', 'error')
        return redirect(url_for('profile.index', tab='info'))

    current_user.avatar = f'/static/{path}'
    try:
        db.session.commit()
        flash('头像已更新', 'success')
    except Exception:
        db.session.rollback()
        flash('头像更新失败', 'error')

    return redirect(url_for('profile.index', tab='info'))


@profile_bp.route('/send_password_code', methods=['POST'])
@login_required
def send_password_code():
    """生成 6 位数字验证码并通过 KOOK Bot 私聊发送给当前用户。"""
    if not current_user.kook_bound or not current_user.kook_id:
        return jsonify({'ok': False, 'msg': '请先绑定 KOOK 账号才能修改密码'}), 400

    now = int(time.time())
    last_send = session.get(_PWD_CODE_LAST_SEND_KEY, 0)
    if last_send and now - last_send < _PWD_CODE_RESEND_INTERVAL:
        wait = _PWD_CODE_RESEND_INTERVAL - (now - last_send)
        return jsonify({'ok': False, 'msg': f'请等待 {wait} 秒后再重新发送'}), 429

    code = ''.join(secrets.choice('0123456789') for _ in range(6))

    from app.services.kook_service import send_direct_message
    text = (
        f'【修改密码验证码】\n'
        f'你的验证码是: **{code}**\n'
        f'有效期 5 分钟,请勿泄露给他人。\n'
        f'若非本人操作请忽略此消息。'
    )
    ok = send_direct_message(current_user.kook_id, text)
    if not ok:
        return jsonify({'ok': False, 'msg': '验证码发送失败,请检查 KOOK 是否可接收 Bot 私信'}), 500

    session[_PWD_CODE_SESSION_KEY] = code
    session[_PWD_CODE_EXPIRES_KEY] = now + _PWD_CODE_TTL
    session[_PWD_CODE_USER_KEY] = current_user.id
    session[_PWD_CODE_LAST_SEND_KEY] = now
    return jsonify({'ok': True, 'msg': '验证码已通过 KOOK 私聊发送,请注意查收'})


@profile_bp.route('/change_password', methods=['POST'])
@login_required
def change_password():
    """修改密码: 校验旧密码 + KOOK 验证码 + 新密码强度。"""
    old_password = request.form.get('old_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    code = request.form.get('code', '').strip()

    if not current_user.check_password(old_password):
        flash('当前密码错误', 'error')
        return redirect(url_for('profile.index', tab='info'))

    if len(new_password) < 6:
        flash('新密码长度至少 6 位', 'error')
        return redirect(url_for('profile.index', tab='info'))

    if new_password != confirm_password:
        flash('两次输入的新密码不一致', 'error')
        return redirect(url_for('profile.index', tab='info'))

    saved_code = session.get(_PWD_CODE_SESSION_KEY)
    expires = session.get(_PWD_CODE_EXPIRES_KEY, 0)
    saved_user = session.get(_PWD_CODE_USER_KEY)
    if not saved_code or saved_user != current_user.id:
        flash('请先获取验证码', 'error')
        return redirect(url_for('profile.index', tab='info'))
    if int(time.time()) > expires:
        flash('验证码已过期,请重新获取', 'error')
        return redirect(url_for('profile.index', tab='info'))
    if code != saved_code:
        flash('验证码错误', 'error')
        return redirect(url_for('profile.index', tab='info'))

    current_user.set_password(new_password)
    try:
        db.session.commit()
        for key in (_PWD_CODE_SESSION_KEY, _PWD_CODE_EXPIRES_KEY,
                    _PWD_CODE_USER_KEY, _PWD_CODE_LAST_SEND_KEY):
            session.pop(key, None)
        flash('密码已修改成功', 'success')
    except Exception:
        db.session.rollback()
        flash('密码修改失败', 'error')

    return redirect(url_for('profile.index', tab='info'))
