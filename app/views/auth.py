import json
import re
import secrets
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User
from app.extensions import db, login_manager

auth_bp = Blueprint('auth', __name__)


def _wechat_oauth_enabled():
    app_id = (current_app.config.get('WECHAT_APP_ID') or '').strip()
    app_secret = (current_app.config.get('WECHAT_APP_SECRET') or '').strip()
    return bool(app_id and app_secret)


def _wechat_redirect_uri():
    configured = (current_app.config.get('WECHAT_OAUTH_REDIRECT_URI') or '').strip()
    if configured:
        return configured
    site_url = (current_app.config.get('SITE_URL') or current_app.config.get('PUBLIC_SITE_URL') or '').strip()
    if site_url:
        return f"{site_url.rstrip('/')}{url_for('auth.wechat_oauth_callback')}"
    return url_for('auth.wechat_oauth_callback', _external=True)


def _wechat_get_json(url):
    req = Request(url, headers={'User-Agent': 'peiwan-admin/1.0'})
    with urlopen(req, timeout=12) as resp:
        raw = resp.read().decode('utf-8', errors='ignore')
    return json.loads(raw)


def _wechat_exchange_code(code):
    params = {
        'appid': current_app.config.get('WECHAT_APP_ID'),
        'secret': current_app.config.get('WECHAT_APP_SECRET'),
        'code': code,
        'grant_type': 'authorization_code',
    }
    url = f"https://api.weixin.qq.com/sns/oauth2/access_token?{urlencode(params)}"
    data = _wechat_get_json(url)
    if data.get('errcode'):
        return None, None, None, f"{data.get('errmsg', '微信换取 token 失败')}({data.get('errcode')})"
    return data.get('access_token'), data.get('openid'), data.get('unionid'), None


def _wechat_fetch_userinfo(access_token, openid):
    params = {
        'access_token': access_token,
        'openid': openid,
        'lang': 'zh_CN',
    }
    url = f"https://api.weixin.qq.com/sns/userinfo?{urlencode(params)}"
    data = _wechat_get_json(url)
    if data.get('errcode'):
        return None, f"{data.get('errmsg', '拉取微信用户信息失败')}({data.get('errcode')})"
    return data, None


def _generate_wechat_username(nickname, openid):
    text = (nickname or '').strip()
    # 保留 ASCII 账号字符，避免登录用户名包含特殊字符
    cleaned = re.sub(r'[^a-zA-Z0-9_]+', '', text).lower()[:18]
    base = f"wx_{cleaned or (openid or 'user')[-10:]}"
    base = base[:40]

    candidate = base
    idx = 1
    while User.query.filter_by(username=candidate).first():
        idx += 1
        suffix = f"_{idx}"
        candidate = f"{base[:max(1, 40 - len(suffix))]}{suffix}"
        if idx > 9999:
            candidate = f"wx_{secrets.token_hex(6)}"
            if not User.query.filter_by(username=candidate).first():
                break
    return candidate

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('profile.index'))
        
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

            return redirect(url_for('profile.index'))
        else:
            flash('用户名或密码错误', 'error')
            
    return render_template('auth/login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('profile.index'))
        
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
        # 注册新用户默认添加老板+陪玩身份标签（主角色仍按所选 role）
        new_user.tag_list = ['老板', '陪玩']
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        flash('注册成功，请登录', 'success')
        return redirect(url_for('auth.login'))
        
    return render_template('auth/register.html')


@auth_bp.route('/wechat/start')
def wechat_oauth_start():
    """微信 OAuth 起点（扫码授权）"""
    if current_user.is_authenticated:
        return redirect(url_for('profile.index'))

    if not _wechat_oauth_enabled():
        flash('微信注册未配置，请先在服务器设置 WECHAT_APP_ID / WECHAT_APP_SECRET', 'error')
        return redirect(url_for('auth.register'))

    mode = (request.args.get('mode') or 'login').strip().lower()
    if mode not in ('login', 'register'):
        mode = 'login'
    role = (request.args.get('role') or 'god').strip().lower()
    if role not in ('god', 'player'):
        role = 'god'

    state = secrets.token_urlsafe(24)
    session['wechat_oauth_state'] = state
    session['wechat_oauth_mode'] = mode
    session['wechat_oauth_role'] = role
    session['wechat_oauth_next'] = (request.args.get('next') or '').strip()

    authorize_base = (
        current_app.config.get('WECHAT_OAUTH_AUTHORIZE_URL')
        or 'https://open.weixin.qq.com/connect/qrconnect'
    ).strip()
    params = {
        'appid': current_app.config.get('WECHAT_APP_ID'),
        'redirect_uri': _wechat_redirect_uri(),
        'response_type': 'code',
        'scope': (current_app.config.get('WECHAT_OAUTH_SCOPE') or 'snsapi_login').strip(),
        'state': state,
    }
    authorize_url = f"{authorize_base}?{urlencode(params)}#wechat_redirect"
    return redirect(authorize_url)


@auth_bp.route('/wechat/callback')
def wechat_oauth_callback():
    """微信 OAuth 回调（登录/注册）"""
    if current_user.is_authenticated:
        return redirect(url_for('profile.index'))

    expected_state = session.pop('wechat_oauth_state', None)
    mode = session.pop('wechat_oauth_mode', 'login')
    role = session.pop('wechat_oauth_role', 'god')
    next_page = session.pop('wechat_oauth_next', '')

    if request.args.get('error'):
        flash(f"微信授权失败: {request.args.get('error_description') or request.args.get('error')}", 'error')
        return redirect(url_for('auth.register' if mode == 'register' else 'auth.login'))

    code = (request.args.get('code') or '').strip()
    state = (request.args.get('state') or '').strip()
    if not code:
        flash('微信授权失败：缺少 code', 'error')
        return redirect(url_for('auth.register' if mode == 'register' else 'auth.login'))
    if not expected_state or state != expected_state:
        flash('微信授权失败：状态校验不通过，请重试', 'error')
        return redirect(url_for('auth.register' if mode == 'register' else 'auth.login'))

    try:
        access_token, openid, _unionid, err = _wechat_exchange_code(code)
    except Exception as e:
        flash(f'微信授权失败：换取 token 异常（{e}）', 'error')
        return redirect(url_for('auth.register' if mode == 'register' else 'auth.login'))
    if err or not access_token or not openid:
        flash(f'微信授权失败：{err or "未获取到 openid"}', 'error')
        return redirect(url_for('auth.register' if mode == 'register' else 'auth.login'))

    user = User.query.filter_by(wechat_openid=openid).first()
    userinfo = None
    try:
        userinfo, info_err = _wechat_fetch_userinfo(access_token, openid)
        if info_err:
            userinfo = None
    except Exception:
        userinfo = None

    if user:
        if not user.status:
            flash('该微信绑定账号已被禁用，请联系管理员', 'error')
            return redirect(url_for('auth.login'))

        # 微信登录时同步基础资料
        user.wechat_bound = True
        if userinfo and userinfo.get('headimgurl'):
            user.avatar = userinfo.get('headimgurl')
        db.session.commit()

        login_user(
            user,
            remember=True,
            duration=current_app.config.get('REMEMBER_COOKIE_DURATION'),
        )
        flash('微信登录成功', 'success')
        if next_page:
            return redirect(next_page)
        return redirect(url_for('profile.index'))

    if mode != 'register':
        flash('该微信还未注册，请先使用微信注册', 'error')
        return redirect(url_for('auth.register'))

    role = role if role in ('god', 'player') else 'god'
    wx_nickname = ((userinfo or {}).get('nickname') or '').strip()
    avatar = (userinfo or {}).get('headimgurl')
    username = _generate_wechat_username(wx_nickname, openid)
    display_name = wx_nickname or f"微信用户{openid[-6:]}"

    new_user = User(
        username=username,
        role=role,
        nickname=display_name if role == 'god' else None,
        player_nickname=display_name if role == 'player' else None,
        wechat_openid=openid,
        wechat_bound=True,
        avatar=avatar or None,
        status=True,
        register_type='wechat',
    )
    # 默认多身份标签
    new_user.tag_list = ['老板', '陪玩']
    # 微信注册账号默认随机密码，可后续由管理员重置
    new_user.set_password(secrets.token_urlsafe(18))

    db.session.add(new_user)
    db.session.commit()

    login_user(
        new_user,
        remember=True,
        duration=current_app.config.get('REMEMBER_COOKIE_DURATION'),
    )
    flash('微信注册成功，已自动登录', 'success')
    if next_page:
        return redirect(next_page)
    return redirect(url_for('profile.index'))

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
