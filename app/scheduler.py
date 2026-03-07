"""
APScheduler 定时任务配置
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler()


def init_scheduler(app):
    """初始化并启动调度器"""

    def auto_confirm_orders():
        """自动确认任务已停用：陪玩订单需老板手动确认"""
        with app.app_context():
            return

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

    scheduler.add_job(
        auto_settle_escort_orders,
        trigger=IntervalTrigger(minutes=5),
        id='auto_settle_escort_orders',
        name='兜底自动结算护航/代练订单',
        replace_existing=True
    )

    scheduler.add_job(
        auto_draw_lotteries,
        trigger=IntervalTrigger(seconds=5),
        id='auto_draw_lotteries',
        name='自动开奖到期抽奖',
        replace_existing=True
    )

    scheduler.add_job(
        update_lottery_counts,
        trigger=IntervalTrigger(seconds=10),
        id='update_lottery_counts',
        name='更新抽奖参与人数',
        replace_existing=True
    )

    def birthday_dm_job():
        """生日私信播报任务（北京时间）"""
        with app.app_context():
            from app.services.kook_service import run_birthday_dm_job
            count = run_birthday_dm_job()
            if count > 0:
                app.logger.info(f'[Scheduler] 生日祝福私信发送 {count} 人')

    def weekly_withdraw_reminder_job():
        """周定时提现提醒任务（北京时间）"""
        with app.app_context():
            from app.services.kook_service import run_weekly_withdraw_reminder_job
            count = run_weekly_withdraw_reminder_job()
            if count > 0:
                app.logger.info(f'[Scheduler] 定时提现提醒发送 {count} 条')

    scheduler.add_job(
        birthday_dm_job,
        trigger=IntervalTrigger(minutes=30),
        id='birthday_dm_job',
        name='生日私信播报',
        replace_existing=True
    )

    scheduler.add_job(
        weekly_withdraw_reminder_job,
        trigger=IntervalTrigger(minutes=1),
        id='weekly_withdraw_reminder_job',
        name='周定时提现提醒',
        replace_existing=True
    )

    scheduler.start()
    app.logger.info('[Scheduler] 定时任务已启动')
