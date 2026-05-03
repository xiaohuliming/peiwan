import json
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request
from sqlalchemy import func, or_

from app.extensions import db
from app.models.story_game import (
    StoryCharacterRelation,
    StoryDirectMessage,
    StoryHardState,
    StoryMemoryFragment,
    StoryPlayerState,
    StoryTurnLog,
)
from app.models.user import User
from app.services.story_memory_service import memory_health_status
from app.utils.permissions import admin_required


story_game_admin_bp = Blueprint('story_game_admin', __name__, template_folder='../templates')


WORLD_LABELS = {
    'source_op': '源能行动部',
    'grey_extract': '灰区撤离线',
    'tactical_club': '战术俱乐部线',
}

BACKGROUND_LABELS = {
    'amnesiac_subject': '失忆实验体',
    'tactical_analyst': '新晋战术分析员',
    'trainee_agent': '预备干员',
    'medical_support': '医疗支援新人',
    'tech_intern': '技术部门实习生',
}

MISSION_STATUS_LABELS = {
    'active': '进行中',
    'completed': '已完成',
    'blocked': '受阻',
    'failed': '失败',
}


def _label(mapping, value, fallback='未设置'):
    if not value:
        return fallback
    return mapping.get(value, value)


def _load_json(raw, default):
    if not raw:
        return default() if callable(default) else default
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default() if callable(default) else default
    return data


def _pretty_json(raw):
    data = _load_json(raw, {})
    return json.dumps(data, ensure_ascii=False, indent=2) if data else ''


def _count_map(model, kook_ids):
    if not kook_ids:
        return {}
    rows = (
        db.session.query(model.kook_id, func.count(model.id))
        .filter(model.kook_id.in_(kook_ids))
        .group_by(model.kook_id)
        .all()
    )
    return {kook_id: count for kook_id, count in rows}


def _build_stats():
    since = datetime.utcnow() - timedelta(hours=24)
    return {
        'players': StoryPlayerState.query.count(),
        'active_24h': StoryTurnLog.query.filter(StoryTurnLog.created_at >= since).count(),
        'turns': StoryTurnLog.query.count(),
        'memories': StoryMemoryFragment.query.count(),
        'pending_dms': StoryDirectMessage.query.filter(
            StoryDirectMessage.reply_allowed.is_(True),
            StoryDirectMessage.replied_at.is_(None),
        ).count(),
    }


def _load_detail(state):
    if not state:
        return None

    hard_state = StoryHardState.query.filter_by(kook_id=state.kook_id).first()
    relations = (
        StoryCharacterRelation.query
        .filter_by(kook_id=state.kook_id)
        .order_by(StoryCharacterRelation.id.asc())
        .all()
    )
    memories = (
        StoryMemoryFragment.query
        .filter_by(kook_id=state.kook_id)
        .order_by(StoryMemoryFragment.unlocked_at.desc())
        .limit(30)
        .all()
    )
    dms = (
        StoryDirectMessage.query
        .filter_by(kook_id=state.kook_id)
        .order_by(StoryDirectMessage.created_at.desc())
        .limit(30)
        .all()
    )
    turn_rows = (
        StoryTurnLog.query
        .filter_by(kook_id=state.kook_id)
        .order_by(StoryTurnLog.created_at.desc())
        .limit(20)
        .all()
    )
    turns = [
        {
            'row': row,
            'updates_pretty': _pretty_json(row.state_updates),
        }
        for row in turn_rows
    ]

    return {
        'state': state,
        'hard_state': hard_state,
        'world_label': _label(WORLD_LABELS, state.story_world),
        'background_label': _label(BACKGROUND_LABELS, state.background),
        'mission_status_label': _label(
            MISSION_STATUS_LABELS,
            hard_state.mission_status if hard_state else None,
        ),
        'flags': state.flag_list,
        'traits': state.trait_map,
        'choices': state.choice_list,
        'inventory': hard_state.inventory_map if hard_state else {},
        'npc_states': hard_state.npc_state_map if hard_state else {},
        'relations': relations,
        'memories': memories,
        'dms': dms,
        'turns': turns,
    }


@story_game_admin_bp.route('/')
@admin_required
def index():
    page = request.args.get('page', 1, type=int)
    q = (request.args.get('q') or '').strip()
    world = (request.args.get('world') or '').strip()
    chapter = request.args.get('chapter', type=int)

    query = StoryPlayerState.query.outerjoin(User, StoryPlayerState.user_id == User.id)
    if q:
        like = f'%{q}%'
        query = query.filter(or_(
            StoryPlayerState.kook_id.ilike(like),
            StoryPlayerState.kook_username.ilike(like),
            StoryPlayerState.status_label.ilike(like),
            User.username.ilike(like),
            User.nickname.ilike(like),
            User.player_nickname.ilike(like),
            User.kook_id.ilike(like),
            User.kook_username.ilike(like),
        ))
    if world:
        query = query.filter(StoryPlayerState.story_world == world)
    if chapter is not None:
        query = query.filter(StoryPlayerState.chapter == chapter)

    states = (
        query.order_by(StoryPlayerState.updated_at.desc(), StoryPlayerState.id.desc())
        .paginate(page=page, per_page=20, error_out=False)
    )
    kook_ids = [state.kook_id for state in states.items]
    counts = {
        'turns': _count_map(StoryTurnLog, kook_ids),
        'memories': _count_map(StoryMemoryFragment, kook_ids),
        'dms': _count_map(StoryDirectMessage, kook_ids),
    }

    selected_kook_id = (request.args.get('kook_id') or '').strip()
    selected = None
    if selected_kook_id:
        selected = StoryPlayerState.query.filter_by(kook_id=selected_kook_id).first()
    if selected is None and states.items:
        selected = states.items[0]

    return render_template(
        'admin/story_game.html',
        states=states,
        stats=_build_stats(),
        memory_health=memory_health_status(check_connection=False),
        counts=counts,
        detail=_load_detail(selected),
        q=q,
        world=world,
        chapter=chapter,
        world_labels=WORLD_LABELS,
        background_labels=BACKGROUND_LABELS,
    )
