from flask import Flask, session
from flask_login import current_user
from sqlalchemy import inspect, text
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
    _ensure_gift_schema_compat(app)
    _ensure_broadcast_schema_compat(app)

    # 确保 app_configs 表存在
    with app.app_context():
        try:
            from app.models.app_config import AppConfig  # noqa: F401
            insp = inspect(db.engine)
            if 'app_configs' not in set(insp.get_table_names()):
                AppConfig.__table__.create(db.engine)
                app.logger.info('[Schema] app_configs 表已创建')
        except Exception as e:
            app.logger.warning(f'[Schema] app_configs 表创建失败: {e}')

    # Register blueprints
    from app.views.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)

    from app.views.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')


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

    from app.views.identity_tag_admin import identity_tag_admin_bp
    app.register_blueprint(identity_tag_admin_bp, url_prefix='/admin/identity-tags')

    from app.views.logs import logs_bp
    app.register_blueprint(logs_bp, url_prefix='/admin/logs')

    from app.views.broadcast_admin import broadcast_admin_bp
    app.register_blueprint(broadcast_admin_bp, url_prefix='/admin/broadcast')

    from app.views.export import export_bp
    app.register_blueprint(export_bp, url_prefix='/export')

    from app.views.upgrade_admin import upgrade_admin_bp
    app.register_blueprint(upgrade_admin_bp, url_prefix='/admin/upgrades')
    from app.views.vip_admin import vip_admin_bp
    app.register_blueprint(vip_admin_bp, url_prefix='/admin/vip')

    from app.views.system import system_bp
    app.register_blueprint(system_bp, url_prefix='/admin/system')

    from app.views.lottery_admin import lottery_admin_bp
    app.register_blueprint(lottery_admin_bp, url_prefix='/admin/lottery')

    from app.views.chat_stats_admin import chat_stats_admin_bp
    app.register_blueprint(chat_stats_admin_bp, url_prefix='/admin/chat-stats')

    from app.views.story_game_admin import story_game_admin_bp
    app.register_blueprint(story_game_admin_bp, url_prefix='/admin/story-game')

    from app.views.assistant import assistant_bp
    app.register_blueprint(assistant_bp, url_prefix='/assistant')

    # Register permission helpers as template globals
    from app.utils import permissions as perm
    from app.utils.time_utils import fmt_dt
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
    app.jinja_env.globals['fmt_dt'] = fmt_dt
    app.jinja_env.filters['bj'] = fmt_dt

    # 启动时自动补齐数据库字段（避免新字段导致其他路由500）
    with app.app_context():
        try:
            from app.views.gift_admin import _ensure_gift_sort_order_column
            _ensure_gift_sort_order_column()
        except Exception as e:
            app.logger.warning(f'[Startup] 礼物字段补齐失败: {e}')

        # 补齐用户匿名设置字段
        try:
            from sqlalchemy import inspect as sa_inspect, text as sa_text
            insp = sa_inspect(db.engine)
            user_cols = {c['name'] for c in insp.get_columns('users')}
            anon_cols = [
                ('anonymous_recharge', 'BOOLEAN DEFAULT 0'),
                ('anonymous_consume', 'BOOLEAN DEFAULT 0'),
                ('anonymous_gift_send', 'BOOLEAN DEFAULT 0'),
                ('anonymous_gift_recv', 'BOOLEAN DEFAULT 0'),
                ('anonymous_upgrade', 'BOOLEAN DEFAULT 0'),
                ('anonymous_ranking', 'BOOLEAN DEFAULT 0'),
                ('commission_rate', 'DECIMAL(5,2)'),
            ]
            for col_name, col_type in anon_cols:
                if col_name not in user_cols:
                    db.session.execute(sa_text(f'ALTER TABLE users ADD COLUMN {col_name} {col_type}'))
                    app.logger.info(f'[Startup] 补齐 users.{col_name}')
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.warning(f'[Startup] 用户匿名字段补齐失败: {e}')

        # 补齐 vip_levels 表字段
        try:
            from sqlalchemy import inspect as sa_inspect2, text as sa_text2
            insp2 = sa_inspect2(db.engine)
            if 'vip_levels' in insp2.get_table_names():
                vip_cols = {c['name'] for c in insp2.get_columns('vip_levels')}
                if 'kook_role_id' not in vip_cols:
                    db.session.execute(sa_text2('ALTER TABLE vip_levels ADD COLUMN kook_role_id VARCHAR(100)'))
                    db.session.commit()
                    app.logger.info('[Startup] 补齐 vip_levels.kook_role_id')
        except Exception as e:
            db.session.rollback()
            app.logger.warning(f'[Startup] VIP字段补齐失败: {e}')

    _notif_cache = {}  # {user_id: (timestamp, result)}
    _NOTIF_TTL = 30  # 缓存30秒

    @app.context_processor
    def inject_top_notifications():
        if not current_user.is_authenticated:
            return {'top_notifications': {'total': 0, 'items': []}}
        try:
            import time
            uid = current_user.id
            now = time.time()
            cached = _notif_cache.get(uid)
            if cached and (now - cached[0]) < _NOTIF_TTL:
                return {'top_notifications': cached[1]}
            from app.services.notification_service import get_top_notifications
            result = get_top_notifications(current_user)
            _notif_cache[uid] = (now, result)
            # 清理过期缓存，防止内存泄漏
            if len(_notif_cache) > 200:
                expired = [k for k, v in _notif_cache.items() if (now - v[0]) > _NOTIF_TTL * 2]
                for k in expired:
                    _notif_cache.pop(k, None)
            return {'top_notifications': result}
        except Exception as e:
            app.logger.warning(f'[Notification] 聚合失败: {e}')
            return {'top_notifications': {'total': 0, 'items': []}}

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


def _ensure_gift_schema_compat(app):
    """兼容旧库 gifts 表字段（sort_order/deleted_at/crown_broadcast_template）。"""
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            tables = set(inspector.get_table_names())
            if 'gifts' not in tables:
                return

            cols = {c.get('name') for c in inspector.get_columns('gifts')}
            altered = False
            added_columns = []

            if 'deleted_at' not in cols:
                db.session.execute(text('ALTER TABLE gifts ADD COLUMN deleted_at DATETIME NULL'))
                altered = True
                added_columns.append('deleted_at')

            if 'sort_order' not in cols:
                db.session.execute(text('ALTER TABLE gifts ADD COLUMN sort_order INT NOT NULL DEFAULT 0'))
                altered = True
                added_columns.append('sort_order')

            if 'crown_broadcast_template' not in cols:
                db.session.execute(text('ALTER TABLE gifts ADD COLUMN crown_broadcast_template TEXT NULL'))
                altered = True
                added_columns.append('crown_broadcast_template')

            if altered:
                db.session.commit()
                app.logger.info('[Schema] gifts 兼容字段已补齐: %s', ','.join(added_columns))

            # gift_orders 表兼容字段
            if 'gift_orders' in tables:
                go_cols = {c.get('name') for c in inspector.get_columns('gift_orders')}
                go_altered = False
                go_added = []
                for col_name in ('boss_paid_coin', 'boss_paid_gift'):
                    if col_name not in go_cols:
                        db.session.execute(text(f'ALTER TABLE gift_orders ADD COLUMN {col_name} DECIMAL(10,2) NOT NULL DEFAULT 0'))
                        go_altered = True
                        go_added.append(col_name)
                if go_altered:
                    db.session.commit()
                    app.logger.info('[Schema] gift_orders 兼容字段已补齐: %s', ','.join(go_added))

        except Exception as e:
            db.session.rollback()
            app.logger.warning(f'[Schema] gifts 兼容字段补齐失败: {e}')


def _ensure_broadcast_schema_compat(app):
    """兼容旧库 broadcast_configs 表字段（target_level）。"""
    with app.app_context():
        try:
            inspector = inspect(db.engine)
            tables = set(inspector.get_table_names())
            if 'broadcast_configs' not in tables:
                return

            cols = {c.get('name') for c in inspector.get_columns('broadcast_configs')}
            if 'target_level' in cols:
                return

            db.session.execute(text('ALTER TABLE broadcast_configs ADD COLUMN target_level VARCHAR(50) NULL'))
            db.session.commit()
            app.logger.info('[Schema] broadcast_configs 兼容字段已补齐: target_level')
        except Exception as e:
            db.session.rollback()
            app.logger.warning(f'[Schema] broadcast_configs 兼容字段补齐失败: {e}')


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
