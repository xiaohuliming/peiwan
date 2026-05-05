from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import case, func

from app.extensions import db
from app.models.minigame import MiniGameRating, MiniGameRecord
from app.models.user import User
from app.services.minigame_service import (
    BLACKJACK_TIER_EMOJI,
    blackjack_tier,
    game_label,
)
from app.utils.permissions import admin_required


minigame_admin_bp = Blueprint('minigame_admin', __name__, template_folder='../templates')


GAME_KEYS = ['hangman', 'scramble', 'mastermind', 'blackjack', 'connect4']
GAME_OPTIONS = [(k, game_label(k)) for k in GAME_KEYS]
RESULT_LABELS = {
    'win': '胜',
    'loss': '负',
    'draw': '平',
    'abandoned': '弃局',
}


def _parse_int(value, default, min_v=1, max_v=365):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_v, min(max_v, n))


def _user_display_name(user):
    if not user:
        return ''
    return user.player_nickname or user.kook_username or user.nickname or user.username or f'#{user.id}'


def _build_user_lookup_by_kook_ids(kook_ids):
    cleaned = [k for k in {str(k or '').strip() for k in kook_ids} if k]
    if not cleaned:
        return {}
    rows = User.query.filter(User.kook_id.in_(cleaned)).all()
    return {u.kook_id: u for u in rows}


@minigame_admin_bp.route('/')
@login_required
@admin_required
def index():
    days = _parse_int(request.args.get('days', 7), default=7, min_v=1, max_v=90)
    game_filter = (request.args.get('game') or '').strip()
    if game_filter and game_filter not in GAME_KEYS:
        game_filter = ''

    now = datetime.utcnow()
    since = now - timedelta(days=days)
    since_24h = now - timedelta(hours=24)

    # ============ KPI ============
    total_games = MiniGameRecord.query.count()
    games_in_window = MiniGameRecord.query.filter(MiniGameRecord.ended_at >= since).count()
    games_24h = MiniGameRecord.query.filter(MiniGameRecord.ended_at >= since_24h).count()

    # 独立玩家(基于 kook_id)
    p1_kids = {row[0] for row in db.session.query(MiniGameRecord.player1_kook_id)
                                            .filter(MiniGameRecord.player1_kook_id.isnot(None)).all()}
    p2_kids = {row[0] for row in db.session.query(MiniGameRecord.player2_kook_id)
                                            .filter(MiniGameRecord.player2_kook_id.isnot(None)).all()}
    unique_players = len(p1_kids | p2_kids)
    rated_players_bj = MiniGameRating.query.filter_by(game='blackjack').count()

    kpi = {
        'total_games': total_games,
        'games_in_window': games_in_window,
        'games_24h': games_24h,
        'unique_players': unique_players,
        'rated_players_bj': rated_players_bj,
    }

    # ============ 各游戏概况(窗口内) ============
    per_game_rows = (
        db.session.query(
            MiniGameRecord.game,
            func.count(MiniGameRecord.id).label('count'),
            func.avg(MiniGameRecord.duration_seconds).label('avg_dur'),
            func.avg(MiniGameRecord.moves).label('avg_moves'),
            func.sum(case((MiniGameRecord.result == 'abandoned', 1), else_=0)).label('abandons'),
        )
        .filter(MiniGameRecord.ended_at >= since)
        .group_by(MiniGameRecord.game)
        .all()
    )
    per_game = []
    for row in per_game_rows:
        cnt = int(row.count or 0)
        per_game.append({
            'game': row.game,
            'label': game_label(row.game),
            'count': cnt,
            'avg_duration': round(float(row.avg_dur or 0), 1),
            'avg_moves': round(float(row.avg_moves or 0), 1),
            'abandons': int(row.abandons or 0),
            'abandon_rate': round((int(row.abandons or 0) * 100 / cnt), 1) if cnt else 0.0,
        })
    per_game.sort(key=lambda x: x['count'], reverse=True)
    window_total = sum(item['count'] for item in per_game) or 1
    for item in per_game:
        item['ratio'] = round(item['count'] * 100 / window_total, 1)

    # ============ 21 点排位榜 Top 20 ============
    bj_ratings = (
        MiniGameRating.query
        .filter_by(game='blackjack')
        .order_by(MiniGameRating.rating.desc(),
                  MiniGameRating.peak_rating.desc(),
                  MiniGameRating.games_played.asc())
        .limit(20)
        .all()
    )
    bj_user_map = {}
    if bj_ratings:
        bj_user_map = {u.id: u for u in User.query.filter(
            User.id.in_([r.user_id for r in bj_ratings])).all()}
    bj_rows = []
    for rating_row in bj_ratings:
        u = bj_user_map.get(rating_row.user_id)
        tier = blackjack_tier(rating_row.rating)
        bj_rows.append({
            'user': u,
            'display_name': _user_display_name(u) or f'用户#{rating_row.user_id}',
            'rating': int(rating_row.rating or 0),
            'peak': int(rating_row.peak_rating or 0),
            'streak': int(rating_row.win_streak or 0),
            'games_played': int(rating_row.games_played or 0),
            'tier': tier,
            'tier_emoji': BLACKJACK_TIER_EMOJI.get(tier, '🏅'),
            'updated_at': rating_row.updated_at,
        })

    # ============ 玩家活跃榜(窗口内, 按对局数) ============
    p1_q = (
        db.session.query(
            MiniGameRecord.player1_kook_id.label('kook_id'),
            func.count(MiniGameRecord.id).label('games'),
            func.sum(case((MiniGameRecord.winner_kook_id == MiniGameRecord.player1_kook_id, 1), else_=0)).label('wins'),
        )
        .filter(MiniGameRecord.ended_at >= since)
        .filter(MiniGameRecord.player1_kook_id.isnot(None))
        .group_by(MiniGameRecord.player1_kook_id)
    )
    p2_q = (
        db.session.query(
            MiniGameRecord.player2_kook_id.label('kook_id'),
            func.count(MiniGameRecord.id).label('games'),
            func.sum(case((MiniGameRecord.winner_kook_id == MiniGameRecord.player2_kook_id, 1), else_=0)).label('wins'),
        )
        .filter(MiniGameRecord.ended_at >= since)
        .filter(MiniGameRecord.player2_kook_id.isnot(None))
        .group_by(MiniGameRecord.player2_kook_id)
    )
    activity = defaultdict(lambda: {'games': 0, 'wins': 0})
    for row in list(p1_q.all()) + list(p2_q.all()):
        kid = str(row.kook_id or '').strip()
        if not kid:
            continue
        activity[kid]['games'] += int(row.games or 0)
        activity[kid]['wins'] += int(row.wins or 0)

    activity_list = []
    if activity:
        sorted_items = sorted(activity.items(), key=lambda kv: kv[1]['games'], reverse=True)[:20]
        kids = [kid for kid, _ in sorted_items]
        user_lookup = _build_user_lookup_by_kook_ids(kids)
        for kid, item in sorted_items:
            u = user_lookup.get(kid)
            games = item['games']
            wins = item['wins']
            activity_list.append({
                'kook_id': kid,
                'user': u,
                'display_name': _user_display_name(u) or kid,
                'games': games,
                'wins': wins,
                'win_rate': round(wins * 100 / games, 1) if games else 0.0,
            })

    # ============ 最近对局(支持游戏筛选) ============
    recent_q = MiniGameRecord.query.order_by(MiniGameRecord.ended_at.desc())
    if game_filter:
        recent_q = recent_q.filter_by(game=game_filter)
    recent_records = recent_q.limit(50).all()
    # 把可能未持久化的 kook_id 解析名字
    extra_kids = set()
    for rec in recent_records:
        if rec.player1_kook_id and not rec.player1_user_id:
            extra_kids.add(rec.player1_kook_id)
        if rec.player2_kook_id and not rec.player2_user_id:
            extra_kids.add(rec.player2_kook_id)
    extra_user_lookup = _build_user_lookup_by_kook_ids(extra_kids)

    recent_rows = []
    for rec in recent_records:
        p1_user = rec.player1_user or extra_user_lookup.get(rec.player1_kook_id or '')
        p2_user = rec.player2_user or extra_user_lookup.get(rec.player2_kook_id or '')
        winner_user = rec.winner_user or extra_user_lookup.get(rec.winner_kook_id or '')
        recent_rows.append({
            'id': rec.id,
            'game_label': rec.game_label or game_label(rec.game),
            'channel_id': rec.channel_id or '',
            'p1_name': _user_display_name(p1_user) or rec.player1_name or rec.player1_kook_id or '匿名',
            'p2_name': _user_display_name(p2_user) or rec.player2_name or rec.player2_kook_id or '',
            'has_p2': bool(rec.player2_kook_id),
            'winner_name': _user_display_name(winner_user) or rec.winner_name or '',
            'result': rec.result,
            'result_label': RESULT_LABELS.get(rec.result, rec.result),
            'end_reason': rec.end_reason or '',
            'moves': int(rec.moves or 0),
            'duration': int(rec.duration_seconds or 0),
            'ended_at': rec.ended_at,
        })

    return render_template(
        'admin/minigame.html',
        days=days,
        game_filter=game_filter,
        game_options=GAME_OPTIONS,
        kpi=kpi,
        per_game=per_game,
        bj_rows=bj_rows,
        activity_rows=activity_list,
        recent_rows=recent_rows,
    )
