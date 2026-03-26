from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from app.extensions import db
from app.models.intimacy import Intimacy
from app.utils.permissions import admin_required
from app.services import upload_service
from app.services import kook_service
from app.services.intimacy_service import clear_intimacy

system_bp = Blueprint('system', __name__)

@system_bp.route('/')
@login_required
@admin_required
def index():
    """系统工具首页"""
    intimacy_count = Intimacy.query.count()

    # KOOK 注册标签配置
    from app.models.app_config import AppConfig
    register_god_kook_role = AppConfig.get('register_god_kook_role_id', '')
    register_player_kook_role = AppConfig.get('register_player_kook_role_id', '')

    # 获取 KOOK 服务器标签列表
    kook_roles = []
    try:
        from app.services.kook_service import fetch_kook_role_catalog
        result, err = fetch_kook_role_catalog()
        if not err and result:
            kook_roles = result.get('roles', []) if isinstance(result, dict) else []
    except Exception:
        pass

    return render_template('system/index.html',
        intimacy_count=intimacy_count,
        kook_roles=kook_roles,
        register_god_kook_role=register_god_kook_role,
        register_player_kook_role=register_player_kook_role,
    )

@system_bp.route('/upload', methods=['POST'])
@login_required
@admin_required
def upload():
    """通用文件上传接口"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '没有文件部分'})
    
    file = request.files['file']
    subfolder = request.form.get('type', 'misc') # gifts, avatars, receipts
    
    path, error = upload_service.save_file(file, subfolder)
    
    if error:
        return jsonify({'success': False, 'message': error})
        
    return jsonify({
        'success': True, 
        'url': f"/static/{path}",
        'path': path
    })


@system_bp.route('/intimacy/clear', methods=['POST'])
@login_required
@admin_required
def clear_intimacy_data():
    """清空指定日期之前的亲密度数据"""
    before_date_str = request.form.get('before_date', '').strip()
    if not before_date_str:
        flash('请选择清空日期', 'error')
        return redirect(url_for('system.index'))

    try:
        before_date = datetime.strptime(before_date_str, '%Y-%m-%d')
    except ValueError:
        flash('日期格式错误', 'error')
        return redirect(url_for('system.index'))

    try:
        count = clear_intimacy(before_date, operator_id=current_user.id)
        db.session.commit()
        flash(f'已清空 {before_date_str} 之前的亲密度数据，共 {count} 条', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'清空失败: {e}', 'error')

    return redirect(url_for('system.index'))


@system_bp.route('/do_clear_intimacy', methods=['POST'])
@login_required
@admin_required
def do_clear_intimacy():
    """兼容旧模板动作"""
    return clear_intimacy_data()


@system_bp.route('/bot/test', methods=['POST'])
@login_required
@admin_required
def bot_test():
    """兼容旧模板动作: 发送测试频道消息"""
    channel_id = request.form.get('channel_id', '').strip()
    title = request.form.get('title', '').strip() or '调测消息'
    content = request.form.get('content', '').strip()
    msg_type = request.form.get('msg_type', 'success')

    if not channel_id or not content:
        flash('频道ID和内容不能为空', 'error')
        return redirect(url_for('system.index'))

    ok = kook_service.send_test_message(channel_id, title, content, msg_type=msg_type)
    if ok:
        flash('测试消息发送成功', 'success')
    else:
        flash('测试消息发送失败，请检查 KOOK 配置和频道ID', 'error')
    return redirect(url_for('system.index'))

@system_bp.route('/bot/debug', methods=['GET', 'POST'])
@login_required
@admin_required
def bot_debug():
    """机器人调测页面"""
    result = None
    
    if request.method == 'POST':
        action = request.form.get('action')
        target_id = request.form.get('target_id') # kook_id
        content = request.form.get('content')
        
        if action == 'send_dm':
            # 发送私信
            try:
                # 这里假设 kook_service 有一个通用的发送方法，或者我们直接调用 api
                # 暂时用 send_direct_message 模拟
                success = kook_service.send_direct_message(target_id, content)
                result = {'success': success, 'message': '发送成功' if success else '发送失败'}
            except Exception as e:
                result = {'success': False, 'message': str(e)}
                
        elif action == 'test_card':
            # 测试普通消息（无卡片边框）
            try:
                text = f'**Bot 调测消息**\n{content or ""}'
                success = kook_service.send_direct_message(target_id, text)
                result = {'success': success, 'message': '消息发送成功' if success else '发送失败'}
            except Exception as e:
                result = {'success': False, 'message': str(e)}

    return render_template('system/bot_debug.html', result=result)


@system_bp.route('/register-kook-roles', methods=['POST'])
@login_required
@admin_required
def save_register_kook_roles():
    """保存注册自动授予 KOOK 标签配置"""
    from app.models.app_config import AppConfig

    god_role_id = request.form.get('register_god_kook_role_id', '').strip()
    player_role_id = request.form.get('register_player_kook_role_id', '').strip()

    AppConfig.set('register_god_kook_role_id', god_role_id, '注册老板自动授予的KOOK标签ID')
    AppConfig.set('register_player_kook_role_id', player_role_id, '注册陪玩自动授予的KOOK标签ID')
    db.session.commit()

    flash('注册 KOOK 标签配置已保存', 'success')
    return redirect(url_for('system.index'))


@system_bp.route('/test-grant-role', methods=['POST'])
@login_required
@admin_required
def test_grant_role():
    """调测: 手动测试 KOOK 标签授予"""
    from app.models.user import User

    user_id = request.form.get('user_id', '').strip()
    role_id = request.form.get('role_id', '').strip()

    if not user_id or not role_id:
        flash('请填写用户ID和标签ID', 'error')
        return redirect(url_for('system.index'))

    user = User.query.get(int(user_id))
    if not user:
        flash(f'用户 #{user_id} 不存在', 'error')
        return redirect(url_for('system.index'))

    if not user.kook_id:
        flash(f'用户 #{user_id} 未绑定 KOOK', 'error')
        return redirect(url_for('system.index'))

    # 同步调用（不用 _async_send），这样能直接看到结果
    try:
        from app.services.kook_service import grant_kook_role
        grant_kook_role(user, role_id)
        flash(f'标签授予已执行: user={user.kook_id}, role_id={role_id}，请检查 KOOK 服务器是否生效', 'success')
    except Exception as e:
        flash(f'标签授予异常: {e}', 'error')

    return redirect(url_for('system.index'))
