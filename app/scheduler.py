"""
APScheduler 定时任务配置
"""
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

scheduler = BackgroundScheduler()
_app_ref = None  # 保持对 Flask app 的引用


def init_scheduler(app):
    """初始化并启动调度器"""

    def auto_confirm_orders():
        """24h 自动确认陪玩单（仅 normal）"""
        with app.app_context():
            from datetime import datetime, timedelta
            from app.extensions import db
            from app.models.order import Order
            from app.services.order_service import confirm_order
            from app.services.kook_service import push_order_confirm

            now = datetime.utcnow()
            overdue = now - timedelta(hours=24)
            order_type_expr = db.func.lower(db.func.coalesce(Order.order_type, 'normal'))
            deadline_expr = db.func.coalesce(
                Order.report_time,
                Order.fill_time,
                Order.created_at,
            )

            orders = Order.query.filter(
                Order.status == 'pending_confirm',
                order_type_expr.notin_(['escort', 'training']),
                db.or_(
                    Order.auto_confirm_at <= now,
                    deadline_expr <= overdue,
                )
            ).all()

            count = 0
            failed = 0
            for order in orders:
                ok, err = confirm_order(order)
                if ok:
                    count += 1
                    try:
                        # 自动确认后通知陪玩
                        push_order_confirm(order)
                    except Exception as e:
                        app.logger.warning(f'[Scheduler] 自动确认通知失败 order={order.order_no}: {e}')
                else:
                    failed += 1
                    app.logger.warning(f'[Scheduler] 自动确认失败 order={order.order_no}: {err}')

            if count > 0:
                db.session.commit()
                app.logger.info(f'[Scheduler] 24h自动确认陪玩订单 {count} 笔')
            elif failed > 0:
                db.session.rollback()
                app.logger.warning(f'[Scheduler] 24h自动确认执行完成，失败 {failed} 笔')

    def auto_clock_timeout():
        """4小时打卡超时检测"""
        with app.app_context():
            from datetime import datetime, timedelta
            from app.extensions import db
            from app.models.clock import ClockRecord

            cutoff = datetime.utcnow() - timedelta(hours=4)
            records = ClockRecord.query.filter(
                ClockRecord.status == 'clocked_in',
                ClockRecord.clock_in <= cutoff
            ).all()

            count = 0
            for r in records:
                r.status = 'auto_timeout'
                r.clock_out = datetime.utcnow()
                delta = r.clock_out - r.clock_in
                r.duration_minutes = int(delta.total_seconds() / 60)
                count += 1
            if count > 0:
                db.session.commit()
                app.logger.info(f'[Scheduler] 超时处理 {count} 条打卡记录')

    def batch_vip_check():
        """VIP等级批量检查"""
        with app.app_context():
            from app.services.vip_service import batch_check_upgrades
            count = batch_check_upgrades()
            if count > 0:
                app.logger.info(f'[Scheduler] VIP升级 {count} 位用户')

    # 注册任务
    scheduler.add_job(
        auto_confirm_orders,
        trigger=IntervalTrigger(minutes=5),
        id='auto_confirm_orders',
        name='24h自动确认订单',
        next_run_time=datetime.utcnow(),
        replace_existing=True
    )

    scheduler.add_job(
        auto_clock_timeout,
        trigger=IntervalTrigger(minutes=10),
        id='auto_clock_timeout',
        name='4h打卡超时检测',
        replace_existing=True
    )

    scheduler.add_job(
        batch_vip_check,
        trigger=IntervalTrigger(hours=1),
        id='batch_vip_check',
        name='VIP等级批量检查',
        replace_existing=True
    )

    def auto_settle_escort_orders():
        """兜底自动结算历史 pending_pay 护航/代练订单"""
        with app.app_context():
            from app.extensions import db
            from app.models.order import Order
            from app.services.order_service import settle_escort_order

            orders = Order.query.filter(
                Order.status == 'pending_pay',
                Order.order_type.in_(['escort', 'training']),
                Order.freeze_status == 'normal',
            ).all()

            count = 0
            for order in orders:
                ok, err = settle_escort_order(order)
                if ok:
                    count += 1
                else:
                    app.logger.warning(
                        f'[Scheduler] 护航/代练自动结算失败 order={order.order_no}: {err}'
                    )
            if count > 0:
                db.session.commit()
                app.logger.info(f'[Scheduler] 自动结算护航/代练 {count} 笔')

    def auto_draw_lotteries():
        """自动开奖到期抽奖"""
        with app.app_context():
            from app.services.lottery_service import check_and_draw_due_lotteries
            count = check_and_draw_due_lotteries()
            if count > 0:
                app.logger.info(f'[Scheduler] 自动开奖 {count} 个抽奖')

    def update_lottery_counts():
        """更新已发布抽奖的参与人数（兜底，Bot 事件也会实时更新）"""
        with app.app_context():
            from app.services.lottery_service import update_all_published_lottery_counts
            update_all_published_lottery_counts()

    def settle_chat_daily_rankings():
        """每日发言排行榜结算（北京时间 00:05 结算前一天）。"""
        with app.app_context():
            from app.services.chat_stats_service import settle_daily
            count, _ = settle_daily()
            if count > 0:
                app.logger.info(f'[Scheduler] 每日发言排行结算 {count} 人')

    def settle_chat_weekly_rankings():
        """每周发言排行榜结算（周一北京时间 00:10 结算上一周）。"""
        with app.app_context():
            from app.services.chat_stats_service import settle_weekly
            count, _ = settle_weekly()
            if count > 0:
                app.logger.info(f'[Scheduler] 每周发言排行结算 {count} 人')

    def voice_truncate_orphans():
        """兜底：把 active 但超过 truncate_hours 的语音会话强制关闭"""
        with app.app_context():
            from app.services.voice_stats_service import truncate_orphan_sessions
            count = truncate_orphan_sessions()
            if count > 0:
                app.logger.info(f'[Scheduler] 强制结算挂机会话 {count} 条')

    def voice_split_cross_day():
        """每天 00:01 把仍 active 的语音会话在昨日 23:59:59 截断、今日 00:00:00 起接续"""
        with app.app_context():
            from app.services.voice_stats_service import split_cross_day_sessions
            count = split_cross_day_sessions()
            if count > 0:
                app.logger.info(f'[Scheduler] 跨日切分挂机会话 {count} 条')

    scheduler.add_job(
        auto_settle_escort_orders,
        trigger=IntervalTrigger(minutes=5),
        id='auto_settle_escort_orders',
        name='兜底自动结算护航/代练订单',
        replace_existing=True
    )

    scheduler.add_job(
        auto_draw_lotteries,
        trigger=IntervalTrigger(seconds=30),
        id='auto_draw_lotteries',
        name='自动开奖到期抽奖',
        replace_existing=True
    )

    scheduler.add_job(
        update_lottery_counts,
        trigger=IntervalTrigger(seconds=60),
        id='update_lottery_counts',
        name='更新抽奖参与人数',
        replace_existing=True
    )

    try:
        import pytz
        bj_tz = pytz.timezone('Asia/Shanghai')
    except ImportError:
        from datetime import timezone, timedelta
        bj_tz = timezone(timedelta(hours=8), name='Asia/Shanghai')
    scheduler.add_job(
        settle_chat_daily_rankings,
        trigger=CronTrigger(hour=0, minute=5, timezone=bj_tz),
        id='settle_chat_daily_rankings',
        name='每日发言排行榜结算',
        replace_existing=True
    )

    scheduler.add_job(
        settle_chat_weekly_rankings,
        trigger=CronTrigger(day_of_week=0, hour=0, minute=10, timezone=bj_tz),
        id='settle_chat_weekly_rankings',
        name='每周发言排行榜结算',
        replace_existing=True
    )

    scheduler.add_job(
        voice_truncate_orphans,
        trigger=IntervalTrigger(minutes=5),
        id='voice_truncate_orphans',
        name='挂机会话兜底截断',
        replace_existing=True
    )

    scheduler.add_job(
        voice_split_cross_day,
        trigger=CronTrigger(hour=0, minute=1, timezone=bj_tz),
        id='voice_split_cross_day',
        name='挂机会话跨日切分',
        replace_existing=True
    )

    def birthday_broadcast_job():
        """生日播报任务（北京时间）"""
        with app.app_context():
            from app.services.kook_service import run_birthday_broadcast_job
            count = run_birthday_broadcast_job()
            if count > 0:
                app.logger.info(f'[Scheduler] 生日祝福播报 {count} 人')

    scheduler.add_job(
        birthday_broadcast_job,
        trigger=IntervalTrigger(minutes=30),
        id='birthday_dm_job',
        name='生日播报',
        replace_existing=True
    )

    # 保存 app 引用供 sync 函数使用
    global _app_ref
    _app_ref = app

    # 启动调度器
    scheduler.start()
    app.logger.info('[Scheduler] 定时任务已启动')

    # 从数据库加载所有提现提醒配置，注册精确 CronTrigger
    sync_weekly_reminder_jobs(app)


def sync_weekly_reminder_jobs(app=None):
    """
    同步数据库中的 weekly_withdraw_reminder 配置到 APScheduler CronTrigger。
    在启动时 / 管理员增删改配置后调用。
    """
    app = app or _app_ref
    if not app:
        return

    with app.app_context():
        from app.models.broadcast import BroadcastConfig
        try:
            import pytz
            BJ_TZ = pytz.timezone('Asia/Shanghai')
        except ImportError:
            from datetime import timezone, timedelta
            BJ_TZ = timezone(timedelta(hours=8), name='Asia/Shanghai')

        # 1. 清理所有旧的 weekly_reminder cron job
        existing_jobs = scheduler.get_jobs()
        for job in existing_jobs:
            if job.id.startswith('weekly_reminder_'):
                scheduler.remove_job(job.id)

        # 2. 为每条启用的配置注册精确 CronTrigger
        configs = BroadcastConfig.query.filter_by(
            broadcast_type='weekly_withdraw_reminder',
            status=True,
        ).all()

        for cfg in configs:
            if not cfg.channel_id:
                continue

            weekday = int(cfg.schedule_weekday if cfg.schedule_weekday is not None else 6)
            time_str = cfg.schedule_time or '12:00'
            parts = time_str.split(':')
            try:
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
            except (ValueError, IndexError):
                hour, minute = 12, 0

            # APScheduler day_of_week: 0=Mon ... 6=Sun（与 Python weekday 一致）
            job_id = f'weekly_reminder_{cfg.id}'
            config_id = cfg.id  # 闭包捕获

            def _make_job_func(cid):
                def _job():
                    with app.app_context():
                        from app.services.kook_service import send_weekly_reminder_for_config
                        ok = send_weekly_reminder_for_config(cid)
                        if ok:
                            app.logger.info(f'[Scheduler] 定时提现提醒已发送 config_id={cid}')
                return _job

            scheduler.add_job(
                _make_job_func(config_id),
                trigger=CronTrigger(
                    day_of_week=weekday,
                    hour=hour,
                    minute=minute,
                    timezone=BJ_TZ,
                ),
                id=job_id,
                name=f'提现提醒 #{cfg.id} 周{"一二三四五六日"[weekday]} {hour:02d}:{minute:02d}',
                replace_existing=True,
            )

        app.logger.info(f'[Scheduler] 已同步 {len(configs)} 条提现提醒 CronTrigger')
