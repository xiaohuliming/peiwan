"""
APScheduler 定时任务配置
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler()


def init_scheduler(app):
    """初始化并启动调度器"""

    def auto_confirm_orders():
        """24小时自动确认订单"""
        with app.app_context():
            from datetime import datetime
            from app.extensions import db
            from app.models.order import Order
            from app.services.order_service import confirm_order

            orders = Order.query.filter(
                Order.status == 'pending_confirm',
                Order.freeze_status == 'normal',
                Order.auto_confirm_at != None,
                Order.auto_confirm_at <= datetime.utcnow()
            ).all()

            count = 0
            for order in orders:
                ok, _ = confirm_order(order)
                if ok:
                    count += 1
            if count > 0:
                db.session.commit()
                app.logger.info(f'[Scheduler] 自动确认 {count} 笔订单')

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

    scheduler.start()
    app.logger.info('[Scheduler] 定时任务已启动')
