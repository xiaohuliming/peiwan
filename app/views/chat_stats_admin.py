from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.chat_stats import ChatRankSettlement
from app.services import chat_stats_service
from app.services.log_service import log_operation
from app.utils.permissions import admin_required


chat_stats_admin_bp = Blueprint('chat_stats_admin', __name__, template_folder='../templates')


def _parse_date_arg(raw_value):
    text = str(raw_value or '').strip()
    if not text:
        return chat_stats_service.bj_today()
    try:
        return datetime.strptime(text[:10], '%Y-%m-%d').date()
    except ValueError:
        return chat_stats_service.bj_today()


@chat_stats_admin_bp.route('/')
@login_required
@admin_required
def index():
    cfg = chat_stats_service.get_config(create=True)
    db.session.commit()

    selected_date = _parse_date_arg(request.args.get('date'))
    week_start, week_end = chat_stats_service.week_range(selected_date)
    rank_limit = int(cfg.rank_limit or 10)

    daily_ranking = chat_stats_service.get_daily_ranking(selected_date, limit=rank_limit)
    weekly_ranking = chat_stats_service.get_weekly_ranking(selected_date, limit=rank_limit)
    daily_totals = chat_stats_service.get_daily_totals(selected_date)
    recent_checkins = chat_stats_service.get_recent_checkins(limit=50)
    milestone_rewards = cfg.get_milestone_rewards()

    daily_settlements = (
        ChatRankSettlement.query
        .filter_by(period_type='daily', period_start=selected_date, period_end=selected_date)
        .order_by(ChatRankSettlement.rank_no.asc())
        .all()
    )
    weekly_settlements = (
        ChatRankSettlement.query
        .filter_by(period_type='weekly', period_start=week_start, period_end=week_end)
        .order_by(ChatRankSettlement.rank_no.asc())
        .all()
    )

    return render_template(
        'admin/chat_stats.html',
        cfg=cfg,
        selected_date=selected_date,
        week_start=week_start,
        week_end=week_end,
        daily_ranking=daily_ranking,
        weekly_ranking=weekly_ranking,
        daily_settlements=daily_settlements,
        weekly_settlements=weekly_settlements,
        daily_totals=daily_totals,
        recent_checkins=recent_checkins,
        milestone_rewards=milestone_rewards,
        channel_text=chat_stats_service.join_id_lines(cfg.channel_id_list),
        whitelist_text=chat_stats_service.join_id_lines(cfg.whitelist_kook_id_list),
    )


@chat_stats_admin_bp.route('/config', methods=['POST'])
@login_required
@admin_required
def save_config():
    cfg = chat_stats_service.update_config_from_form(request.form)
    db.session.commit()
    log_operation(current_user.id, 'chat_stats_config', 'chat_stat_config', cfg.id, '更新 KOOK 发言统计机器人配置')
    db.session.commit()
    flash('发言统计机器人配置已保存', 'success')
    return redirect(url_for('chat_stats_admin.index', date=request.form.get('selected_date') or None))


@chat_stats_admin_bp.route('/settle', methods=['POST'])
@login_required
@admin_required
def settle():
    period = request.form.get('period', 'daily')
    selected_date = _parse_date_arg(request.form.get('selected_date'))
    force = request.form.get('force') == 'on'

    if period == 'weekly':
        count, rows = chat_stats_service.settle_weekly(selected_date, force=force)
        detail = f'手动结算每周发言排行: {selected_date:%Y-%m-%d}'
    else:
        count, rows = chat_stats_service.settle_daily(selected_date, force=force)
        detail = f'手动结算每日发言排行: {selected_date:%Y-%m-%d}'

    log_operation(current_user.id, 'chat_stats_settle', 'chat_rank_settlement', None, detail)
    db.session.commit()
    if count:
        flash(f'结算完成，生成 {count} 条排行记录', 'success')
    elif rows:
        flash('该周期已结算，如需重算请勾选“覆盖已有结算”', 'info')
    else:
        flash('该周期暂无可结算的有效发言', 'info')
    return redirect(url_for('chat_stats_admin.index', date=selected_date.isoformat()))
