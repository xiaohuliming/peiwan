from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User
from app.extensions import db, login_manager

auth_bp = Blueprint('auth', __name__)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            if not user.status:
                flash('该账号已被禁用，请联系管理员', 'error')
                return render_template('auth/login.html')
                
            login_user(
                user,
                remember=True,
                duration=current_app.config.get('REMEMBER_COOKIE_DURATION'),
            )
            next_page = request.args.get('next')
            
            if next_page:
                return redirect(next_page)
            
            # Role-based redirection
            if user.role in ['god', 'player']:
                # TODO: Create specific homepages for GOD and Player
                # For now, redirect to dashboard but it should be customized
                return redirect(url_for('dashboard.index'))
            else:
                return redirect(url_for('dashboard.index'))
        else:
            flash('用户名或密码错误', 'error')
            
    return render_template('auth/login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'god')
        kook_name = request.form.get('kook_name', '').strip()  # abc#1234 格式

        if not username:
            flash('账号不能为空', 'error')
            return render_template('auth/register.html')

        if User.query.filter_by(username=username).first():
            flash('该账号已存在', 'error')
            return render_template('auth/register.html')

        # Validate role
        if role not in ['god', 'player']:
            flash('无效的身份选择', 'error')
            return render_template('auth/register.html')

        # 通过 KOOK 名称查找用户 ID 和头像
        kook_id = None
        kook_username = None
        kook_avatar = None
        display_name = kook_name or username  # 默认优先用填写的 KOOK 名
        if kook_name:
            from app.services.kook_service import search_kook_user_by_name
            kook_id, kook_username, kook_avatar, err = search_kook_user_by_name(kook_name)
            if err:
                flash(f'KOOK 查询失败: {err}', 'error')
                return render_template('auth/register.html')
            # 检查 KOOK ID 是否已被使用
            if kook_id and User.query.filter_by(kook_id=kook_id).first():
                flash('该 KOOK 账号已被其他用户绑定', 'error')
                return render_template('auth/register.html')
            if kook_username:
                display_name = kook_username  # 用 KOOK 名称作为昵称

        new_user = User(
            username=username,
            role=role,
            nickname=display_name if role == 'god' else None,
            player_nickname=display_name if role == 'player' else None,
            kook_id=kook_id,
            kook_username=kook_username,
            kook_bound=bool(kook_id),
            avatar=kook_avatar or None,
            status=True,
            register_type='manual'
        )
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        flash('注册成功，请登录', 'success')
        return redirect(url_for('auth.login'))
        
    return render_template('auth/register.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
