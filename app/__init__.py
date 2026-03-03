from flask import Flask, session
from app.config import Config
from app.extensions import db, migrate, login_manager


def _ensure_ssl_env(app):
    """启动后台任务前兜底 SSL 证书环境，避免 khl(aiohttp) 证书链校验失败。"""
    import os
    import ssl

    ca_candidates = [
        app.config.get('SSL_CERT_FILE'),
        app.config.get('REQUESTS_CA_BUNDLE'),
        os.environ.get('SSL_CERT_FILE'),
        os.environ.get('REQUESTS_CA_BUNDLE'),
        '/etc/ssl/certs/ca-certificates.crt',
        '/etc/pki/tls/certs/ca-bundle.crt',
        '/etc/ssl/cert.pem',
    ]
    ca_file = next((p for p in ca_candidates if p and os.path.exists(p)), None)

    if ca_file:
        os.environ['SSL_CERT_FILE'] = ca_file
        os.environ['REQUESTS_CA_BUNDLE'] = ca_file
        if os.path.isdir('/etc/ssl/certs'):
            os.environ.setdefault('SSL_CERT_DIR', '/etc/ssl/certs')
        app.logger.info(f'[SSL] CA bundle in use: {ca_file}')
    else:
        app.logger.warning('[SSL] 未找到可用 CA bundle，可能导致 HTTPS 证书校验失败')

    # 预热一次 default verify paths，便于日志排查部署环境差异
    try:
        paths = ssl.get_default_verify_paths()
        app.logger.info(f'[SSL] default verify paths: cafile={paths.cafile}, capath={paths.capath}')
    except Exception as e:
        app.logger.warning(f'[SSL] 读取 default verify paths 失败: {e}')


def create_app(config_class=Config, start_background_tasks=True):
    app = Flask(__name__)
    app.config.from_object(config_class)

    @app.before_request
    def _keep_session_permanent():
        # 所有已登录会话都使用永久 session，并由 PERMANENT_SESSION_LIFETIME 控制有效期
        session.permanent = True

    # Initialize Flask extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Register blueprints
    from app.views.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)

    from app.views.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.views.companions import companions_bp
    app.register_blueprint(companions_bp, url_prefix='/companions')

    from app.views.orders import orders_bp
    app.register_blueprint(orders_bp, url_prefix='/orders')
    
    from app.views.profile import profile_bp
    app.register_blueprint(profile_bp, url_prefix='/profile')

    from app.views.finance import finance_bp
    app.register_blueprint(finance_bp, url_prefix='/finance')

    from app.views.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    from app.views.clock import clock_bp
    app.register_blueprint(clock_bp, url_prefix='/clock')

    from app.views.gifts import gifts_bp
    app.register_blueprint(gifts_bp, url_prefix='/gifts')

    from app.views.gift_admin import gift_admin_bp
    app.register_blueprint(gift_admin_bp, url_prefix='/admin/gifts')

    from app.views.users import users_bp
    app.register_blueprint(users_bp, url_prefix='/users')

    from app.views.rankings import rankings_bp
    app.register_blueprint(rankings_bp, url_prefix='/rankings')

    from app.views.project_admin import project_admin_bp
    app.register_blueprint(project_admin_bp, url_prefix='/admin/projects')

    from app.views.account_admin import account_admin_bp
    app.register_blueprint(account_admin_bp, url_prefix='/admin/accounts')

    from app.views.logs import logs_bp
    app.register_blueprint(logs_bp, url_prefix='/admin/logs')

    from app.views.broadcast_admin import broadcast_admin_bp
    app.register_blueprint(broadcast_admin_bp, url_prefix='/admin/broadcast')

    from app.views.export import export_bp
    app.register_blueprint(export_bp, url_prefix='/export')

    from app.views.upgrade_admin import upgrade_admin_bp
    app.register_blueprint(upgrade_admin_bp, url_prefix='/admin/upgrades')

    from app.views.system import system_bp
    app.register_blueprint(system_bp, url_prefix='/admin/system')

    from app.views.lottery_admin import lottery_admin_bp
    app.register_blueprint(lottery_admin_bp, url_prefix='/admin/lottery')

    # Register permission helpers as template globals
    from app.utils import permissions as perm
    app.jinja_env.globals['can_dispatch_order'] = perm.can_dispatch_order
    app.jinja_env.globals['can_freeze_order'] = perm.can_freeze_order
    app.jinja_env.globals['can_refund_order'] = perm.can_refund_order
    app.jinja_env.globals['can_delete_order'] = perm.can_delete_order
    app.jinja_env.globals['can_approve_withdraw'] = perm.can_approve_withdraw
    app.jinja_env.globals['can_manage_users'] = perm.can_manage_users
    app.jinja_env.globals['can_adjust_balance'] = perm.can_adjust_balance
    app.jinja_env.globals['can_manage_accounts'] = perm.can_manage_accounts
    app.jinja_env.globals['can_export_data'] = perm.can_export_data
    app.jinja_env.globals['can_view_stats'] = perm.can_view_stats
    app.jinja_env.globals['can_manage_system'] = perm.can_manage_system

    # APScheduler 定时任务
    if start_background_tasks and not app.config.get('TESTING'):
        try:
            from app.scheduler import init_scheduler
            init_scheduler(app)
        except ImportError:
            app.logger.warning('APScheduler 未安装, 定时任务未启动')

    # KOOK Bot 后台线程 (WebSocket 命令接收)
    if start_background_tasks and app.config.get('KOOK_BOT_ENABLED') and not app.config.get('TESTING'):
        _start_kook_bot(app)

    return app


def _start_kook_bot(app):
    """在后台线程中启动 KOOK Bot WebSocket 连接"""
    import asyncio
    import threading

    _ensure_ssl_env(app)

    token = app.config.get('KOOK_TOKEN', '')
    if not token or token == 'your-kook-bot-token':
        app.logger.warning('[KOOK Bot] Token 未配置，Bot 未启动')
        return

    def run_bot():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from bot.bot import bot
            app.logger.info('[KOOK Bot] 正在后台线程启动...')
            bot.run()
        except Exception as e:
            app.logger.error(f'[KOOK Bot] 启动失败: {e}')
        finally:
            try:
                loop.close()
            except Exception:
                pass

    t = threading.Thread(target=run_bot, daemon=True, name='kook-bot')
    t.start()
    app.logger.info('[KOOK Bot] 后台线程已启动')
