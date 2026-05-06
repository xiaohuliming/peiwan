from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.services.voice_stats_service import (
    bj_today,
    format_duration,
    get_config,
    join_id_lines,
    list_active_sessions,
    list_channel_distribution,
    list_daily_leaderboard,
    list_recent_sessions,
    list_window_leaderboard,
    stats_overview,
    update_config_from_form,
)
from app.utils.permissions import admin_required


voice_admin_bp = Blueprint('voice_admin', __name__, template_folder='../templates')


def _parse_int(value, default, min_v=1, max_v=90):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_v, min(max_v, n))


@voice_admin_bp.route('/', methods=['GET'])
@login_required
@admin_required
def index():
    days = _parse_int(request.args.get('days', 7), default=7, min_v=1, max_v=90)

    cfg = get_config(create=True)
    overview = stats_overview(window_days=days)
    today_date, today_rows = list_daily_leaderboard(target_date=bj_today(), limit=20)
    win_start, win_end, window_rows = list_window_leaderboard(days=days, limit=20)
    ch_start, ch_end, channel_rows = list_channel_distribution(days=days, limit=20)
    active_rows = list_active_sessions(limit=50)
    recent_rows = list_recent_sessions(limit=50)

    config_form = {
        'enabled': bool(cfg.enabled),
        'min_session_seconds': cfg.min_session_seconds,
        'truncate_hours': cfg.truncate_hours,
        'whitelist_channel_ids': join_id_lines(cfg.whitelist_channel_id_list),
        'blacklist_channel_ids': join_id_lines(cfg.blacklist_channel_id_list),
        'whitelist_kook_ids': join_id_lines(cfg.whitelist_kook_id_list),
    }

    return render_template(
        'admin/voice.html',
        days=days,
        cfg=cfg,
        config_form=config_form,
        overview=overview,
        today_date=today_date,
        today_rows=today_rows,
        window_rows=window_rows,
        window_start=win_start,
        window_end=win_end,
        channel_rows=channel_rows,
        active_rows=active_rows,
        recent_rows=recent_rows,
        format_duration=format_duration,
        now_utc=datetime.utcnow(),
    )


@voice_admin_bp.route('/config', methods=['POST'])
@login_required
@admin_required
def save_config():
    update_config_from_form(request.form)
    flash('挂机统计配置已保存', 'success')
    return redirect(url_for('voice_admin.index', days=request.args.get('days', 7)))
