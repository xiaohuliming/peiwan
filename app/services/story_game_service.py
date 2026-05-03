"""
KOOK AI 沉浸式剧情互动游戏服务。

第一版聚焦 Bot 入口：/story start、/story continue、档案、记忆、私信。
"""
import json
import os
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict

import requests
from flask import current_app, has_app_context

from app.extensions import db
from app.models.story_game import (
    StoryCharacterRelation,
    StoryDirectMessage,
    StoryHardState,
    StoryMemoryFragment,
    StoryPlayerState,
    StoryTurnLog,
)
from app.services.story_memory_service import (
    is_memory_enabled,
    memory_status_lines,
    remember_story_turn,
    search_story_memories,
)


WORLD_OPTIONS = {
    'source_op': {
        'order': 1,
        'name': '源能行动部',
        'tagline': '特工、源能、Spike、异常实验与被删除的档案。',
        'opening_scene': 'sealed_training_room',
    },
    'grey_extract': {
        'order': 2,
        'name': '灰区撤离线',
        'tagline': '撤离点、佣兵小队、战地医疗、失联档案与信任危机。',
        'opening_scene': 'grey_zone_checkpoint',
    },
    'tactical_club': {
        'order': 3,
        'name': '战术俱乐部线',
        'tagline': '嗯呢呗战术基地、虚拟训练舱、社群事件与现实交错。',
        'opening_scene': 'ennb_virtual_training_room',
    },
}


BACKGROUND_OPTIONS = {
    'amnesiac_subject': {
        'order': 1,
        'name': '失忆实验体',
        'tagline': '你在封锁区醒来，手腕上只有编号 07。',
    },
    'tactical_analyst': {
        'order': 2,
        'name': '新晋战术分析员',
        'tagline': '你通过情报与判断影响小队行动。',
    },
    'trainee_agent': {
        'order': 3,
        'name': '预备干员',
        'tagline': '你需要通过训练、测试和实战考核。',
    },
    'medical_support': {
        'order': 4,
        'name': '医疗支援新人',
        'tagline': '你从后勤与医疗室开始，被迫面对保护与牺牲。',
    },
    'tech_intern': {
        'order': 5,
        'name': '技术部门实习生',
        'tagline': '你维护基地 AI，却发现档案正在被篡改。',
    },
}


CHARACTER_CARDS = {
    'jett': {
        'order': 1,
        'name': '捷风',
        'role': '高速突破手',
        'story_role': '玩家最早遇到的干员之一，嘴硬但可靠。',
        'personality': ['直接', '嘴硬', '好胜', '行动派', '不轻易表达关心'],
        'speech_style': '短句、直接、带一点挑衅；不要过度温柔，不要长篇说教。',
        'trust_up': ['玩家表现勇敢', '玩家没有逃避危险', '玩家尊重她的判断'],
        'trust_down': ['玩家背叛队友', '玩家把责任推给别人', '玩家试图用一句话摧毁主线'],
        'dm_style': '嘴硬式关心，信息短，但能看出她在意玩家。',
        'route_theme': '从不信任到并肩作战',
    },
    'sage': {
        'order': 2,
        'name': '贤者',
        'role': '医疗与保护者',
        'story_role': '基地中最稳定的照护者，温柔但承担过量责任。',
        'personality': ['温柔', '冷静', '有责任感', '善于观察心理状态'],
        'speech_style': '温和、克制、有安全感；不要空泛鸡汤。',
        'trust_up': ['玩家诚实表达恐惧', '玩家愿意保护他人', '玩家尊重生命'],
        'trust_down': ['玩家轻视伤亡', '玩家利用她的愧疚感'],
        'dm_style': '医疗室夜谈式关心，像留一盏灯。',
        'route_theme': '信任修复与创伤疗愈',
    },
    'omen': {
        'order': 3,
        'name': '幽影',
        'role': '神秘观察者',
        'story_role': '似乎知道玩家过去的一部分，常与记忆碎片和阴影事件相关。',
        'personality': ['神秘', '低语式表达', '像预言也像警告', '不直接回答问题'],
        'speech_style': '短、冷、带隐喻；不要把谜底一次讲清。',
        'trust_up': ['玩家愿意面对真相', '玩家理解被删除身份的痛苦'],
        'trust_down': ['玩家嘲弄他的存在', '玩家逃避所有记忆线索'],
        'dm_style': '谜语式提示，像从黑暗里递来的线索。',
        'route_theme': '失忆、阴影、真相与名字重建',
    },
    'killjoy': {
        'order': 4,
        'name': '奇乐',
        'role': '科技与 AI 线核心',
        'story_role': '负责基地技术系统，把玩家当成异常数据后发现系统更异常。',
        'personality': ['聪明', '语速快', '理性但不冷漠', '爱吐槽', '对异常数据敏感'],
        'speech_style': '快节奏、理性、带吐槽；紧张时用玩笑遮掩。',
        'trust_up': ['玩家配合调查', '玩家提供异常细节', '玩家不乱碰危险系统'],
        'trust_down': ['玩家破坏设备', '玩家隐瞒关键数据'],
        'dm_style': '技术警告、监控录像、系统日志和彩蛋。',
        'route_theme': 'AI 阴谋、档案恢复与系统入侵',
    },
    'sova': {
        'order': 5,
        'name': '猎枭',
        'role': '可靠侦察者',
        'story_role': '冷静可靠的前辈型角色，引导玩家追踪真相。',
        'personality': ['沉稳', '可靠', '观察力强', '像导师', '重视真相'],
        'speech_style': '简洁、耐心、真诚鼓励；不要轻浮。',
        'trust_up': ['玩家耐心追踪线索', '玩家害怕但继续前进'],
        'trust_down': ['玩家急着相信未经验证的结论', '玩家抛弃同伴'],
        'dm_style': '任务复盘、追踪提醒和冷静陪伴。',
        'route_theme': '调查、追踪、耐心与慢热守护',
    },
}


WORLD_ALIASES = {
    '1': 'source_op',
    'a': 'source_op',
    '源能': 'source_op',
    '源能行动部': 'source_op',
    '2': 'grey_extract',
    'b': 'grey_extract',
    '灰区': 'grey_extract',
    '灰区撤离线': 'grey_extract',
    '3': 'tactical_club',
    'c': 'tactical_club',
    '战术': 'tactical_club',
    '战术俱乐部线': 'tactical_club',
}

BACKGROUND_ALIASES = {
    '1': 'amnesiac_subject',
    '失忆': 'amnesiac_subject',
    '失忆实验体': 'amnesiac_subject',
    '2': 'tactical_analyst',
    '分析员': 'tactical_analyst',
    '新晋战术分析员': 'tactical_analyst',
    '3': 'trainee_agent',
    '预备': 'trainee_agent',
    '预备干员': 'trainee_agent',
    '4': 'medical_support',
    '医疗': 'medical_support',
    '医疗支援新人': 'medical_support',
    '5': 'tech_intern',
    '技术': 'tech_intern',
    '技术部门实习生': 'tech_intern',
}

CHARACTER_ALIASES = {
    '1': 'jett',
    '捷风': 'jett',
    'jett': 'jett',
    '2': 'sage',
    '贤者': 'sage',
    'sage': 'sage',
    '3': 'omen',
    '幽影': 'omen',
    'omen': 'omen',
    '4': 'killjoy',
    '奇乐': 'killjoy',
    'killjoy': 'killjoy',
    '5': 'sova',
    '猎枭': 'sova',
    'sova': 'sova',
}

DEFAULT_MEMORY_07 = {
    'memory_id': 'memory_01_number_07',
    'title': '编号 07',
    'content': '你手腕上的编号不是名字，而是某种实验标记。广播里反复出现的“回收编号 07”，像是在确认你不是第一次醒来。',
}

CHAPTER_SCENE_RULES = {
    'source_op': {
        0: {
            'chapter_name': 'Chapter 0：醒来',
            'goal': '从封锁区醒来，与捷风建立临时协作，找到编号 07 与基地 AI 回收指令的第一条线索。',
            'allowed_scene_ids': [
                'sealed_training_room',
                'escape_corridor',
                'abandoned_comm_room',
                'service_storage',
                'medical_observation_room',
            ],
            'terminal_scene_ids': ['abandoned_comm_room', 'medical_observation_room'],
            'completion_flags': ['chapter_0_complete', 'chapter_0_exit_clue_found'],
            'allowed_mission_ids': ['chapter_0_escape', 'chapter_0_find_signal_source'],
            'scenes': {
                'sealed_training_room': {
                    'name': '封锁区训练室',
                    'purpose': '开局醒来、捷风持枪接触、基地 AI 回收广播。',
                    'allowed_next': ['sealed_training_room', 'escape_corridor'],
                },
                'escape_corridor': {
                    'name': '封锁走廊',
                    'purpose': '逃离训练室、遭遇巡逻/机械锁/红色警戒，形成第一次信任考验。',
                    'allowed_next': ['escape_corridor', 'abandoned_comm_room', 'service_storage'],
                },
                'abandoned_comm_room': {
                    'name': '废弃通讯室',
                    'purpose': '接入破碎通讯、听到有人喊出 07，发现档案被删的第一条实证。',
                    'allowed_next': ['abandoned_comm_room', 'escape_corridor', 'service_storage', 'medical_observation_room'],
                },
                'service_storage': {
                    'name': '维护储物间',
                    'purpose': '取得临时工具/通讯器/被撕毁照片，也可能触发陷阱或警报。',
                    'allowed_next': ['service_storage', 'escape_corridor', 'abandoned_comm_room'],
                },
                'medical_observation_room': {
                    'name': '医疗观察室',
                    'purpose': '贤者或医疗档案线索初次出现，暗示玩家曾接受过观察。',
                    'allowed_next': ['medical_observation_room', 'abandoned_comm_room', 'escape_corridor'],
                },
            },
        },
    },
    'grey_extract': {
        0: {
            'chapter_name': 'Chapter 0：撤离点失联',
            'goal': '在灰区检查点确认失联信号来源，建立佣兵小队临时信任。',
            'allowed_scene_ids': ['grey_zone_checkpoint', 'grey_zone_outer_road', 'field_med_tent'],
            'terminal_scene_ids': ['grey_zone_outer_road', 'field_med_tent'],
            'completion_flags': ['chapter_0_complete', 'first_extraction_signal_found'],
            'allowed_mission_ids': ['chapter_0_escape', 'chapter_0_find_signal_source'],
            'scenes': {
                'grey_zone_checkpoint': {
                    'name': '灰区检查点',
                    'purpose': '开局进入撤离线，听到失联小队信号。',
                    'allowed_next': ['grey_zone_checkpoint', 'grey_zone_outer_road', 'field_med_tent'],
                },
                'grey_zone_outer_road': {
                    'name': '灰区外环道路',
                    'purpose': '推进撤离点与失联信号调查。',
                    'allowed_next': ['grey_zone_outer_road', 'grey_zone_checkpoint', 'field_med_tent'],
                },
                'field_med_tent': {
                    'name': '战地医疗帐篷',
                    'purpose': '处理伤情和医疗线索。',
                    'allowed_next': ['field_med_tent', 'grey_zone_checkpoint', 'grey_zone_outer_road'],
                },
            },
        },
    },
    'tactical_club': {
        0: {
            'chapter_name': 'Chapter 0：训练舱异常',
            'goal': '确认嗯呢呗虚拟训练舱异常，发现现实频道与游戏世界开始交错。',
            'allowed_scene_ids': ['ennb_virtual_training_room', 'ennb_command_channel', 'club_backstage'],
            'terminal_scene_ids': ['ennb_command_channel', 'club_backstage'],
            'completion_flags': ['chapter_0_complete', 'training_pod_anomaly_confirmed'],
            'allowed_mission_ids': ['chapter_0_escape', 'chapter_0_find_signal_source'],
            'scenes': {
                'ennb_virtual_training_room': {
                    'name': '嗯呢呗虚拟训练舱',
                    'purpose': '开局从俱乐部训练舱异常醒来。',
                    'allowed_next': ['ennb_virtual_training_room', 'ennb_command_channel', 'club_backstage'],
                },
                'ennb_command_channel': {
                    'name': '嗯呢呗指挥频道',
                    'purpose': '现实 KOOK 频道与剧情系统交错。',
                    'allowed_next': ['ennb_command_channel', 'ennb_virtual_training_room', 'club_backstage'],
                },
                'club_backstage': {
                    'name': '俱乐部后台走廊',
                    'purpose': '调查 Bot 与现实运营后台异常。',
                    'allowed_next': ['club_backstage', 'ennb_command_channel', 'ennb_virtual_training_room'],
                },
            },
        },
    },
}


class StoryContinueGraphState(TypedDict, total=False):
    """LangGraph 主线推进共享状态。"""
    kook_id: str
    user_id: Any
    user_input: str
    resolved_input: str
    channel_id: str
    story_state: Any
    messages: list
    raw_output: str
    repair_raw_output: str
    validation_errors: list
    payload: dict
    visible_text: str
    choices: list
    updates: dict
    created_dms: list
    ok: bool
    message: str
    llm_used: bool
    graph_trace: list
    orchestrator: str


def _option_by_order(options):
    return sorted(options.items(), key=lambda item: item[1]['order'])


def menu_text():
    worlds = '\n'.join(
        f"│ {item['order']}. {item['name']} - {item['tagline']}"
        for _, item in _option_by_order(WORLD_OPTIONS)
    )
    backgrounds = '\n'.join(
        f"│ {item['order']}. {item['name']} - {item['tagline']}"
        for _, item in _option_by_order(BACKGROUND_OPTIONS)
    )
    return (
        "╭─ 灰区档案：AI Story Operation\n"
        "│ KOOK 沉浸式剧情互动 / 角色羁绊 / 记忆碎片\n"
        "├─ 故事世界\n"
        f"{worlds}\n"
        "├─ 身份背景\n"
        f"{backgrounds}\n"
        "├─ 开始方式\n"
        "│ `/story start 1 1` 进入源能行动部 + 失忆实验体\n"
        "│ `/story continue 你的行动` 推进剧情\n"
        "│ `/story profile` 查看档案\n"
        "│ `/story archive` 查看记忆\n"
        "│ `/story dm` 查看角色私信\n"
        "│ `/story memory 关键词` 查看自己的长期记忆召回\n"
        "│ `/story status` 查看 LLM 接入状态\n"
        "╰─ 若要重开：`/story restart 1 1`"
    )


def _clean_text(value, max_len=1200):
    text = str(value or '').strip()
    if len(text) > max_len:
        return text[:max_len].rstrip() + '...'
    return text


def _resolve_alias(raw, aliases):
    key = str(raw or '').strip()
    if not key:
        return None
    return aliases.get(key) or aliases.get(key.lower())


def _world_name(key):
    return WORLD_OPTIONS.get(key, {}).get('name', key or '未知世界')


def _background_name(key):
    return BACKGROUND_OPTIONS.get(key, {}).get('name', key or '未知身份')


def _character_name(character_id):
    return CHARACTER_CARDS.get(character_id, {}).get('name', character_id or '未知角色')


def _clamp(value, low=0, high=100):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return max(low, min(high, number))


def _relation_description(character_id, trust, bond_level=0):
    trust = _clamp(trust)
    if character_id == 'jett':
        if trust < 20:
            return '她仍然把你当成异常目标，但没有立刻开火。'
        if trust < 45:
            return '她嘴上依旧不耐烦，却开始听你把话说完。'
        if trust < 70:
            return '她会把你拽到掩体后面，然后假装那只是顺手。'
        return '她已经愿意把后背交给你，只是不会轻易承认。'
    if character_id == 'sage':
        if trust < 25:
            return '她在观察你的伤口，也在观察你有没有继续硬撑。'
        if trust < 55:
            return '她愿意为你留一盏医疗室的灯。'
        return '她把你的安危放进了自己的责任边界。'
    if character_id == 'omen':
        if trust < 25:
            return '他从阴影里看着你，像在确认某个旧名字。'
        if trust < 55:
            return '他开始把警告留给你，而不是只留给黑暗。'
        return '他没有说真相，但他选择站在你能听见的位置。'
    if character_id == 'killjoy':
        if trust < 25:
            return '她仍把你标记为异常数据，但没有把你交给系统。'
        if trust < 55:
            return '她开始让你看见那些“系统不该存在”的日志。'
        return '她把你列进了自己的临时调查小组，虽然嘴上说只是样本。'
    if character_id == 'sova':
        if trust < 25:
            return '他没有急着相信你，只是耐心追踪你留下的痕迹。'
        if trust < 55:
            return '他开始用前辈的方式提醒你：害怕不等于退缩。'
        return '他相信你会走到真相前，也会在必要时替你照亮路。'
    if trust < 30:
        return '关系仍然疏离。'
    if trust < 65:
        return '关系正在变得稳定。'
    return '关系已经进入深层信任。'


def _bond_level_for_trust(trust):
    trust = _clamp(trust)
    if trust >= 85:
        return 5
    if trust >= 70:
        return 4
    if trust >= 55:
        return 3
    if trust >= 35:
        return 2
    if trust >= 18:
        return 1
    return 0


def _initial_trust(character_id):
    return {
        'jett': 14,
        'sage': 12,
        'omen': 8,
        'killjoy': 8,
        'sova': 10,
    }.get(character_id, 5)


def _make_relation(kook_id, user_id, character_id):
    card = CHARACTER_CARDS[character_id]
    trust = _initial_trust(character_id)
    relation = StoryCharacterRelation(
        kook_id=kook_id,
        user_id=user_id,
        character_id=character_id,
        character_name=card['name'],
        trust=trust,
        bond_level=_bond_level_for_trust(trust),
        relationship_status=_relation_description(character_id, trust),
    )
    relation.event_list = []
    db.session.add(relation)
    return relation


def _ensure_relations(kook_id, user_id=None):
    existing = {
        rel.character_id: rel
        for rel in StoryCharacterRelation.query.filter_by(kook_id=kook_id).all()
    }
    for character_id in CHARACTER_CARDS:
        if character_id not in existing:
            existing[character_id] = _make_relation(kook_id, user_id, character_id)
        elif user_id and existing[character_id].user_id != user_id:
            existing[character_id].user_id = user_id
    return existing


def _ensure_hard_state(kook_id, user_id=None, state=None):
    row = StoryHardState.query.filter_by(kook_id=kook_id).first()
    if row:
        if user_id and row.user_id != user_id:
            row.user_id = user_id
        return row

    location_id = getattr(state, 'current_scene', None) or 'sealed_training_room'
    row = StoryHardState(
        kook_id=kook_id,
        user_id=user_id,
        location_id=location_id,
        location_name=_scene_display_name(location_id),
        mission_id='chapter_0_escape',
        mission_name='逃离封锁区',
        mission_status='active',
        mission_progress=0,
    )
    row.inventory_map = {}
    row.npc_state_map = {
        'jett': {
            'alive': True,
            'status': '警戒接触',
            'location_id': location_id,
            'disposition': '警惕',
        }
    }
    db.session.add(row)
    return row


def _scene_display_name(scene_id):
    return {
        'sealed_training_room': '封锁区训练室',
        'escape_corridor': '封锁走廊',
        'abandoned_comm_room': '废弃通讯室',
        'service_storage': '维护储物间',
        'medical_observation_room': '医疗观察室',
        'grey_zone_checkpoint': '灰区检查点',
        'grey_zone_outer_road': '灰区外环道路',
        'field_med_tent': '战地医疗帐篷',
        'ennb_virtual_training_room': '嗯呢呗虚拟训练舱',
        'ennb_command_channel': '嗯呢呗指挥频道',
        'club_backstage': '俱乐部后台走廊',
    }.get(str(scene_id or '').strip(), str(scene_id or '').strip() or '未知地点')


def _hard_state_context(kook_id, user_id=None, state=None):
    hard = _ensure_hard_state(kook_id, user_id, state)
    return {
        'location': {
            'id': hard.location_id,
            'name': hard.location_name,
        },
        'mission': {
            'id': hard.mission_id,
            'name': hard.mission_name,
            'status': hard.mission_status,
            'progress': hard.mission_progress,
        },
        'inventory': hard.inventory_map,
        'npc_states': hard.npc_state_map,
    }


def _chapter_scene_rule_for_state(state):
    if not state:
        return None
    world_rules = CHAPTER_SCENE_RULES.get(getattr(state, 'story_world', '') or '')
    if not world_rules:
        return None
    return world_rules.get(int(getattr(state, 'chapter', 0) or 0))


def _chapter_scene_rule_context(state):
    rule = _chapter_scene_rule_for_state(state)
    if not rule:
        return {}
    current_scene = getattr(state, 'current_scene', '') or ''
    current_rule = (rule.get('scenes') or {}).get(current_scene, {})
    return {
        'chapter_name': rule.get('chapter_name'),
        'goal': rule.get('goal'),
        'current_scene': current_scene,
        'current_scene_name': current_rule.get('name') or _scene_display_name(current_scene),
        'allowed_next_scene_ids': current_rule.get('allowed_next') or [current_scene],
        'allowed_scenes': [
            {
                'id': scene_id,
                'name': scene.get('name') or _scene_display_name(scene_id),
                'purpose': scene.get('purpose') or '',
                'allowed_next': scene.get('allowed_next') or [],
            }
            for scene_id, scene in (rule.get('scenes') or {}).items()
        ],
        'allowed_mission_ids': rule.get('allowed_mission_ids') or [],
        'terminal_scene_ids': rule.get('terminal_scene_ids') or [],
        'completion_flags': rule.get('completion_flags') or [],
    }


def _add_memory(kook_id, user_id, memory, source_event=''):
    memory = _normalize_memory(memory)
    if not memory:
        return None
    existing = StoryMemoryFragment.query.filter_by(kook_id=kook_id, memory_id=memory['memory_id']).first()
    if existing:
        return existing
    row = StoryMemoryFragment(
        kook_id=kook_id,
        user_id=user_id,
        memory_id=memory['memory_id'],
        title=_clean_text(memory['title'], 120),
        content=_clean_text(memory['content'], 1200),
        source_event=_clean_text(source_event or memory.get('source_event'), 120),
    )
    db.session.add(row)
    return row


def _normalize_memory(memory):
    if not memory:
        return None
    if isinstance(memory, str):
        key = memory.strip()
        if key in ('memory_01', 'memory_01_number_07', '编号 07'):
            return dict(DEFAULT_MEMORY_07)
        return {
            'memory_id': re.sub(r'[^a-zA-Z0-9_\-]+', '_', key)[:80] or f'memory_{int(datetime.utcnow().timestamp())}',
            'title': key[:80],
            'content': '这是一段尚未完全复原的记忆，只有标题清晰地留了下来。',
        }
    if not isinstance(memory, dict):
        return None
    memory_id = _clean_text(memory.get('memory_id') or memory.get('id') or memory.get('title'), 100)
    title = _clean_text(memory.get('title') or memory_id or '未命名记忆', 120)
    content = _clean_text(memory.get('content') or memory.get('text') or '这段记忆尚未完全复原。', 1200)
    if not memory_id:
        memory_id = re.sub(r'[^a-zA-Z0-9_\-]+', '_', title)[:80] or f'memory_{int(datetime.utcnow().timestamp())}'
    return {'memory_id': memory_id, 'title': title, 'content': content, 'source_event': memory.get('source_event')}


def start_story(kook_id, kook_username='', user_id=None, world_arg='', background_arg='', reset=False):
    kook_id = str(kook_id or '').strip()
    if not kook_id:
        return {'ok': False, 'message': '未获取到你的 KOOK 身份，请稍后重试。'}

    world_key = _resolve_alias(world_arg, WORLD_ALIASES)
    background_key = _resolve_alias(background_arg, BACKGROUND_ALIASES)
    if not world_key or not background_key:
        return {'ok': False, 'message': menu_text()}

    if reset:
        StoryTurnLog.query.filter_by(kook_id=kook_id).delete(synchronize_session=False)
        StoryDirectMessage.query.filter_by(kook_id=kook_id).delete(synchronize_session=False)
        StoryMemoryFragment.query.filter_by(kook_id=kook_id).delete(synchronize_session=False)
        StoryCharacterRelation.query.filter_by(kook_id=kook_id).delete(synchronize_session=False)
        StoryHardState.query.filter_by(kook_id=kook_id).delete(synchronize_session=False)
        StoryPlayerState.query.filter_by(kook_id=kook_id).delete(synchronize_session=False)
        db.session.flush()

    existing = StoryPlayerState.query.filter_by(kook_id=kook_id).first()
    if existing:
        return {
            'ok': True,
            'message': (
                "你已经有一份正在运行的剧情档案。\n"
                f"当前：{_world_name(existing.story_world)} / {_background_name(existing.background)} / Chapter {existing.chapter}\n"
                "继续：`/story continue 你的行动`\n"
                "重开：`/story restart 1 1`"
            ),
        }

    scene = WORLD_OPTIONS[world_key]['opening_scene']
    state = StoryPlayerState(
        kook_id=kook_id,
        user_id=user_id,
        kook_username=kook_username or None,
        story_world=world_key,
        background=background_key,
        chapter=0,
        current_scene=scene,
        status_label='基地二级警戒目标',
        last_npc='jett',
        summary='玩家在封锁区醒来，手腕上出现编号 07，基地 AI 正在广播回收指令。',
    )
    state.flag_list = ['memory_07_found', 'base_ai_marked_player']
    state.trait_map = {'诚实倾向': 0, '谨慎倾向': 0, '冲动倾向': 0}
    state.choice_list = ['我不记得了', '你先告诉我这里是哪', '我为什么要相信你']
    db.session.add(state)
    _ensure_relations(kook_id, user_id)
    _ensure_hard_state(kook_id, user_id, state)
    _add_memory(kook_id, user_id, DEFAULT_MEMORY_07, source_event='chapter_0_start')
    db.session.commit()

    return {'ok': True, 'message': _opening_text(state)}


def _opening_text(state):
    world = _world_name(state.story_world)
    background = _background_name(state.background)
    return (
        "╭─ Chapter 0：醒来\n"
        f"│ 世界线：{world}\n"
        f"│ 身份：{background}\n"
        "├─ 封锁区训练室\n"
        "你在冷白色灯光下醒来，手腕内侧有一行被灼进皮肤的编号：07。\n\n"
        "广播声在天花板里反复播放：\n"
        "“异常目标确认。回收编号 07。”\n\n"
        "下一秒，训练室的门被风压撞开。捷风闯进来，枪口稳稳指向你。\n\n"
        "“别动。告诉我，你是谁？”\n\n"
        "你脑海里只剩下一句话：不要相信基地里的 AI。\n"
        "├─ 可选行动\n"
        "A. 我不记得了\n"
        "B. 你先告诉我这里是哪\n"
        "C. 我为什么要相信你\n"
        "D. 自由输入\n"
        "╰─ 继续：`/story continue 你的回答或行动`"
    )


@lru_cache(maxsize=1)
def _load_lore_sections():
    root = Path(__file__).resolve().parents[2]
    game_dir = root / 'game'
    agents = _safe_read(game_dir / 'valorant_agents_lore_cn.md')
    maps = _safe_read(game_dir / 'valorant_maps_lore_cn.md')
    weapons = _safe_read(game_dir / 'valorant_weapons_story_cn.md')

    return {
        'overview': [
            _clean_text(_extract_markdown_section(agents, '世界观速记'), 700),
            _clean_text(_extract_markdown_section(agents, '其他重要角色关系抓手'), 700),
            _clean_text(_extract_markdown_section(weapons, '角色配枪速查'), 650),
        ],
        'agents': _extract_markdown_sections(agents, '角色'),
        'maps': _extract_markdown_sections(maps, '地图'),
        'weapons': _extract_markdown_sections(weapons, '武器'),
    }


def _build_lore_reference(state=None, user_input=''):
    """按当前剧情和玩家输入召回角色/地图/武器参考，避免整本资料塞进 prompt。"""
    library = _load_lore_sections()
    query = _build_lore_query(state, user_input)
    snippets = []

    for overview in library['overview']:
        if overview:
            snippets.append(f"【通用参考】\n{overview}")

    ranked_agents = _rank_lore_sections(library['agents'], query, default_titles=['捷风 / Jett', '贤者 / Sage', '幽影 / Omen', '奇乐 / Killjoy', '猎枭 / Sova'])
    ranked_maps = _rank_lore_sections(library['maps'], query, default_titles=['训练场 / Range'])
    ranked_weapons = _rank_lore_sections(library['weapons'], query, default_titles=['鬼魅 / Ghost', '幻影 / Phantom', '狂徒 / Vandal', '标配 / Classic'])

    for item in ranked_agents[:8]:
        snippets.append(f"【角色参考】{item['title']}\n{_clean_text(item['content'], 520)}")
    for item in ranked_maps[:5]:
        snippets.append(f"【地图参考】{item['title']}\n{_clean_text(item['content'], 420)}")
    for item in ranked_weapons[:6]:
        snippets.append(f"【武器参考】{item['title']}\n{_clean_text(item['content'], 360)}")

    max_chars = int(_story_config('STORY_LORE_MAX_CHARS', 9000))
    return _clean_text('\n\n'.join(snippets), max_chars)


def _build_lore_query(state=None, user_input=''):
    parts = [str(user_input or '')]
    if state:
        parts.extend([
            _world_name(getattr(state, 'story_world', '')),
            _background_name(getattr(state, 'background', '')),
            str(getattr(state, 'current_scene', '') or ''),
            str(getattr(state, 'status_label', '') or ''),
            str(getattr(state, 'summary', '') or ''),
            _character_name(getattr(state, 'last_npc', '')),
            ' '.join(getattr(state, 'choice_list', []) or []),
        ])
        if getattr(state, 'story_world', '') == 'source_op':
            parts.append('源晶 Spike Kingdom VALORANT 训练场 训练室 异常实验 AI')
        elif getattr(state, 'story_world', '') == 'grey_extract':
            parts.append('灰区 撤离点 佣兵 小队 战地医疗 物资箱 失联')
        elif getattr(state, 'story_world', '') == 'tactical_club':
            parts.append('嗯呢呗战术基地 虚拟训练舱 频道事件 现实交错')
        if 'training' in str(getattr(state, 'current_scene', '') or ''):
            parts.append('训练场 Range 训练室 武器测试')
    return ' '.join(parts).lower()


def _safe_read(path):
    try:
        if path.exists():
            return path.read_text(encoding='utf-8')
    except Exception:
        return ''
    return ''


def _extract_markdown_sections(text, source):
    if not text:
        return []
    matches = list(re.finditer(r"^###\s+(.+?)\s*$", text, re.M))
    sections = []
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if title and content:
            sections.append({'source': source, 'title': title, 'content': content})
    return sections


def _extract_markdown_section(text, heading):
    if not text:
        return ''
    pattern = re.compile(rf"^###?\s+{re.escape(heading)}\s*$", re.M)
    match = pattern.search(text)
    if not match:
        return ''
    start = match.start()
    next_match = re.search(r"^###?\s+", text[match.end():], re.M)
    end = match.end() + next_match.start() if next_match else len(text)
    return text[start:end].strip()


def _rank_lore_sections(sections, query, default_titles=None):
    default_titles = set(default_titles or [])
    ranked = []
    for item in sections:
        score = _score_lore_section(item, query)
        if item['title'] in default_titles:
            score += 1
        if score > 0:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]['title']))
    return [item for _, item in ranked]


def _score_lore_section(item, query):
    query = str(query or '').lower()
    title = str(item.get('title') or '')
    content = str(item.get('content') or '')
    haystack = f"{title}\n{content}".lower()
    score = 0

    title_parts = [
        part.strip().lower()
        for part in re.split(r"[/／|｜、,，()（）\s]+", title)
        if part.strip()
    ]
    for part in title_parts:
        if part and part in query:
            score += 8

    thematic_terms = [
        '训练场', '训练室', '源晶', 'spike', 'kingdom', 'ai', '异常', '封锁',
        '撤离', '灰区', '佣兵', '医疗', '物资', '失联', '档案',
        '鬼魅', '幻影', '狂徒', '标配', '冥驹', '戍卫', '短炮', '蜂刺',
        '亚海悬城', '裂变峡谷', '隐世修所', '森寒冬港', '日落之城',
    ]
    for term in thematic_terms:
        term_l = term.lower()
        if term_l in query and term_l in haystack:
            score += 3

    for character in CHARACTER_CARDS.values():
        name = character['name'].lower()
        if name in query and name in haystack:
            score += 5

    return score


def continue_story(kook_id, user_id=None, user_input='', channel_id=None):
    result = _run_story_continue_orchestrator(kook_id, user_id, user_input, channel_id)
    if not result.get('ok'):
        db.session.rollback()
        return {
            'ok': False,
            'message': result.get('message') or _story_llm_failure_message(),
            'llm_used': bool(result.get('llm_used')),
            'orchestrator': result.get('orchestrator') or 'langgraph',
            'graph_trace': result.get('graph_trace') or [],
        }
    return {
        'ok': True,
        'message': result.get('message') or '剧情推进完成。',
        'llm_used': True,
        'orchestrator': result.get('orchestrator') or 'langgraph',
        'graph_trace': result.get('graph_trace') or [],
    }


def _story_llm_failure_message():
    return (
        "AI 剧情引擎没有成功返回内容，本次没有推进剧情。\n"
        "请先确认 `/story status` 显示 API Key 已设置，并重启 KOOK Bot 后再试。"
    )


def _run_story_continue_orchestrator(kook_id, user_id=None, user_input='', channel_id=None):
    initial = {
        'kook_id': str(kook_id or '').strip(),
        'user_id': user_id,
        'user_input': _clean_text(user_input, 1000),
        'channel_id': str(channel_id or ''),
        'ok': True,
        'llm_used': False,
        'graph_trace': [],
    }
    graph = _get_story_continue_graph()
    if graph is not None:
        initial['orchestrator'] = 'langgraph'
        result = graph.invoke(
            initial,
            {
                'configurable': {'thread_id': f"story:{initial['kook_id'] or 'anonymous'}"},
                'recursion_limit': 20,
            },
        )
        result['orchestrator'] = 'langgraph'
        return result
    initial['orchestrator'] = 'sequential'
    result = _run_story_continue_pipeline(initial)
    result['orchestrator'] = 'sequential'
    return result


@lru_cache(maxsize=1)
def _get_story_continue_graph():
    if not _story_config_bool('STORY_LANGGRAPH_ENABLED', True):
        return None
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception as e:
        if has_app_context():
            current_app.logger.warning('[Story] LangGraph 不可用，使用顺序编排: %s', e)
        return None

    graph = StateGraph(StoryContinueGraphState)
    graph.add_node('prepare_context', _story_graph_prepare_context)
    graph.add_node('call_llm', _story_graph_call_llm)
    graph.add_node('validate_payload', _story_graph_validate_payload)
    graph.add_node('persist_turn', _story_graph_persist_turn)
    graph.add_node('dispatch_side_effects', _story_graph_dispatch_side_effects)
    graph.add_edge(START, 'prepare_context')
    graph.add_edge('prepare_context', 'call_llm')
    graph.add_edge('call_llm', 'validate_payload')
    graph.add_edge('validate_payload', 'persist_turn')
    graph.add_edge('persist_turn', 'dispatch_side_effects')
    graph.add_edge('dispatch_side_effects', END)
    return graph.compile(name='kook_story_continue')


def _run_story_continue_pipeline(initial):
    graph_state = dict(initial)
    for node in (
        _story_graph_prepare_context,
        _story_graph_call_llm,
        _story_graph_validate_payload,
        _story_graph_persist_turn,
        _story_graph_dispatch_side_effects,
    ):
        updates = node(graph_state) or {}
        graph_state.update(updates)
    return graph_state


def _story_graph_prepare_context(graph_state: StoryContinueGraphState):
    trace = _append_graph_trace(graph_state, 'prepare_context')
    kook_id = str(graph_state.get('kook_id') or '').strip()
    user_input = _clean_text(graph_state.get('user_input'), 1000)
    if not kook_id:
        return _graph_failure(graph_state, '未获取到你的 KOOK 身份，请稍后重试。', trace)
    if not user_input:
        return _graph_failure(
            graph_state,
            '请输入你的行动，例如：`/story continue 我举起手，说我不记得自己是谁`',
            trace,
        )

    state = StoryPlayerState.query.filter_by(kook_id=kook_id).first()
    if not state:
        return _graph_failure(graph_state, "你还没有剧情档案。\n\n" + menu_text(), trace)
    user_id = graph_state.get('user_id')
    if user_id and state.user_id != user_id:
        state.user_id = user_id
    resolved_input = _expand_choice_input(state, user_input)
    return {
        'story_state': state,
        'resolved_input': resolved_input,
        'messages': _build_story_messages(state, resolved_input),
        'graph_trace': trace,
    }


def _story_graph_call_llm(graph_state: StoryContinueGraphState):
    if _graph_stopped(graph_state):
        return {}
    trace = _append_graph_trace(graph_state, 'call_llm')
    raw = _call_story_llm(graph_state.get('messages') or [])
    if not raw:
        return _graph_failure(graph_state, _story_llm_failure_message(), trace)
    return {'raw_output': raw, 'graph_trace': trace}


def _story_graph_validate_payload(graph_state: StoryContinueGraphState):
    if _graph_stopped(graph_state):
        return {}
    trace = _append_graph_trace(graph_state, 'validate_payload')
    raw = graph_state.get('raw_output')
    story_state = graph_state.get('story_state')
    payload, errors = _parse_and_validate_story_payload(raw, story_state=story_state)
    if payload:
        return {'payload': payload, 'validation_errors': [], 'graph_trace': trace}

    repair_raw = _call_story_llm(
        _build_repair_messages(
            graph_state.get('messages') or [],
            raw,
            errors,
            _story_payload_contract(),
        )
    )
    if not repair_raw:
        return _graph_failure(graph_state, _story_llm_failure_message(), trace, errors)
    payload, repair_errors = _parse_and_validate_story_payload(repair_raw, story_state=story_state)
    if payload:
        trace = trace + ['repair_payload']
        return {
            'payload': payload,
            'repair_raw_output': repair_raw,
            'validation_errors': [],
            'graph_trace': trace,
        }
    all_errors = list(errors or []) + list(repair_errors or [])
    current_app.logger.warning('[Story] LLM 输出校验失败: %s', '; '.join(all_errors))
    return _graph_failure(graph_state, _story_llm_failure_message(), trace, all_errors)


def _story_graph_persist_turn(graph_state: StoryContinueGraphState):
    if _graph_stopped(graph_state):
        return {}
    trace = _append_graph_trace(graph_state, 'persist_turn')
    payload = graph_state.get('payload')
    state = graph_state.get('story_state')
    if not isinstance(payload, dict) or state is None:
        return _graph_failure(graph_state, _story_llm_failure_message(), trace)

    visible_text = _clean_text(payload.get('visible_text'), int(_story_config('STORY_VISIBLE_MAX_CHARS', 3200)))
    choices = _normalize_choices(payload.get('suggested_choices'))
    updates = payload.get('state_updates') if isinstance(payload.get('state_updates'), dict) else {}
    narrative_events = payload.get('narrative_events') if isinstance(payload.get('narrative_events'), list) else []
    if narrative_events:
        updates = dict(updates)
        updates['narrative_events'] = narrative_events

    user_id = graph_state.get('user_id')
    resolved_input = graph_state.get('resolved_input') or graph_state.get('user_input') or ''
    created_dms = _apply_state_updates(
        state,
        updates,
        choices,
        user_id=user_id,
        user_input=resolved_input,
        visible_text=visible_text,
    )
    db.session.add(StoryTurnLog(
        kook_id=state.kook_id,
        user_id=user_id,
        channel_id=str(graph_state.get('channel_id') or ''),
        input_text=resolved_input,
        visible_text=visible_text,
        state_updates=json.dumps(updates, ensure_ascii=False),
        llm_used=True,
    ))
    db.session.commit()
    return {
        'ok': True,
        'message': _format_story_response(visible_text, choices),
        'llm_used': True,
        'visible_text': visible_text,
        'choices': choices,
        'updates': updates,
        'created_dms': created_dms,
        'graph_trace': trace,
    }


def _story_graph_dispatch_side_effects(graph_state: StoryContinueGraphState):
    if _graph_stopped(graph_state) or not graph_state.get('llm_used'):
        return {}
    trace = _append_graph_trace(graph_state, 'dispatch_side_effects')
    state = graph_state.get('story_state')
    _send_created_dms(graph_state.get('created_dms') or [])
    remember_story_turn(
        graph_state.get('kook_id'),
        user_id=graph_state.get('user_id') or getattr(state, 'user_id', None),
        user_input=graph_state.get('resolved_input') or graph_state.get('user_input') or '',
        visible_text=graph_state.get('visible_text') or '',
        metadata={
            'channel_id': str(graph_state.get('channel_id') or ''),
            'scene': getattr(state, 'current_scene', ''),
            'chapter': getattr(state, 'chapter', 0),
            'orchestrator': graph_state.get('orchestrator') or 'langgraph',
        },
    )
    return {'graph_trace': trace}


def _append_graph_trace(graph_state, step):
    trace = list(graph_state.get('graph_trace') or [])
    trace.append(step)
    return trace


def _graph_stopped(graph_state):
    return graph_state.get('ok') is False


def _graph_failure(graph_state, message, trace=None, errors=None):
    return {
        'ok': False,
        'message': message,
        'llm_used': False,
        'validation_errors': list(errors or graph_state.get('validation_errors') or []),
        'graph_trace': trace if trace is not None else _append_graph_trace(graph_state, 'failed'),
    }


def _expand_choice_input(state, user_input):
    text = _clean_text(user_input, 1000)
    key = text.strip().upper()
    choices = list(getattr(state, 'choice_list', []) or [])
    choice_map = {'A': 0, 'B': 1, 'C': 2, 'D': None, '1': 0, '2': 1, '3': 2}
    if key not in choice_map:
        return text
    idx = choice_map[key]
    if idx is None:
        return '自由输入'
    if 0 <= idx < len(choices):
        return choices[idx]
    return text


def _normalize_choices(choices):
    if not isinstance(choices, list):
        return []
    cleaned = []
    for choice in choices[:3]:
        text = _strip_choice_prefix(_clean_text(choice, 100))
        if text:
            cleaned.append(text)
    return cleaned


def _strip_choice_prefix(text):
    text = str(text or '').strip()
    text = re.sub(r'^\s*(?:选项\s*)?[A-Da-d][\.、:：\)]\s*', '', text)
    text = re.sub(r'^\s*(?:选项\s*)?\d{1,2}[\.、:：\)]\s*', '', text)
    return text.strip()


def _format_story_response(visible_text, choices):
    lines = ["╭─ 灰区档案", visible_text.strip()]
    if choices:
        lines.append("├─ 可选行动")
        for idx, choice in enumerate(choices, start=1):
            lines.append(f"{idx}. {choice}")
    lines.append("╰─ 继续自由输入：`/story continue 你的行动`")
    return '\n'.join(lines)


def _generate_llm_story_payload(state, user_input):
    messages = _build_story_messages(state, user_input)
    raw = _call_story_llm(messages)
    if not raw:
        return None
    payload, errors = _parse_and_validate_story_payload(raw, story_state=state)
    if payload:
        return payload

    repair_raw = _call_story_llm(_build_repair_messages(messages, raw, errors, _story_payload_contract()))
    if not repair_raw:
        return None
    payload, errors = _parse_and_validate_story_payload(repair_raw, story_state=state)
    if payload:
        return payload
    current_app.logger.warning('[Story] LLM 输出校验失败: %s', '; '.join(errors))
    return None


def _load_story_history(kook_id):
    max_turns = _story_config_int('STORY_HISTORY_MAX_TURNS', 300)
    max_chars = _story_config_int('STORY_HISTORY_MAX_CHARS', 600000)
    total_turns = StoryTurnLog.query.filter_by(kook_id=kook_id).count()
    if max_turns <= 0 or max_chars <= 0 or total_turns <= 0:
        return [], {
            'included_turns': 0,
            'available_turns': total_turns,
            'max_turns': max_turns,
            'max_chars': max_chars,
            'truncated': total_turns > 0,
        }

    newest_first = (
        StoryTurnLog.query
        .filter_by(kook_id=kook_id)
        .order_by(StoryTurnLog.created_at.desc(), StoryTurnLog.id.desc())
        .limit(max_turns)
        .all()
    )

    selected = []
    used_chars = 0
    truncated_by_chars = False
    for turn in newest_first:
        item = {
            'player_input': _clean_text(turn.input_text, 1200),
            'visible_text': _clean_text(turn.visible_text, 3200),
        }
        item_chars = len(item['player_input']) + len(item['visible_text']) + 80
        if selected and used_chars + item_chars > max_chars:
            truncated_by_chars = True
            break
        if not selected and item_chars > max_chars:
            room = max(600, max_chars - len(item['player_input']) - 80)
            item['visible_text'] = _clean_text(turn.visible_text, room)
            item_chars = len(item['player_input']) + len(item['visible_text']) + 80
        selected.append(item)
        used_chars += item_chars

    selected.reverse()
    included = len(selected)
    return selected, {
        'included_turns': included,
        'available_turns': total_turns,
        'max_turns': max_turns,
        'max_chars': max_chars,
        'truncated': included < total_turns or truncated_by_chars,
    }


def _build_story_messages(state, user_input):
    relations = StoryCharacterRelation.query.filter_by(kook_id=state.kook_id).all()
    memories = (
        StoryMemoryFragment.query
        .filter_by(kook_id=state.kook_id)
        .order_by(StoryMemoryFragment.unlocked_at.desc())
        .limit(8)
        .all()
    )
    story_history, history_meta = _load_story_history(state.kook_id)
    long_term_memories = _load_long_term_memories(state, user_input)
    hard_state = _hard_state_context(state.kook_id, state.user_id, state)
    context = {
        'story_world': _world_name(state.story_world),
        'background': _background_name(state.background),
        'chapter': state.chapter,
        'current_scene': state.current_scene,
        'hard_state': hard_state,
        'status_label': state.status_label,
        'last_npc': _character_name(state.last_npc),
        'opening_context': _opening_text(state),
        'flags': state.flag_list[-20:],
        'summary': state.summary,
        'resolved_player_input': user_input,
        'current_choices': state.choice_list,
        'history_meta': history_meta,
        'story_history': story_history,
        'long_term_memories': long_term_memories,
        'chapter_scene_rules': _chapter_scene_rule_context(state),
        'relations': [
            {
                'character_id': rel.character_id,
                'character_name': rel.character_name,
                'trust': rel.trust,
                'bond_level': rel.bond_level,
                'relationship_status': rel.relationship_status,
            }
            for rel in relations
        ],
        'memories': [{'title': m.title, 'content': m.content} for m in memories],
        'character_cards': CHARACTER_CARDS,
        'lore_reference': _build_lore_reference(state, user_input),
    }
    system_prompt = (
        "你是《灰区档案：AI Story Operation》的导演、旁白和 NPC 扮演者。\n"
        "这是 KOOK 内的 AI 沉浸式剧情互动游戏，不是战斗数值模拟器。\n"
        "所有给玩家看的角色名必须使用中文：捷风、贤者、幽影、奇乐、猎枭；不要输出英文角色名。\n"
        "lore_reference 是可参考的角色、地图、武器资料库片段；资料库角色可以作为背景、支线或路人出现，但只有 character_cards 中的核心角色能写入长期关系、羁绊和私信。\n"
        "long_term_memories 是 mem0 召回的玩家长期记忆，可能来自更早会话；它可补充玩家偏好、承诺、角色称呼、关键选择，但不能覆盖 story_history 里明确发生的最新剧情。\n"
        "hard_state 是数据库权威硬状态，包含当前位置、任务、物品、NPC 生死/状态；剧情正文不能与它冲突。若要改变地点、任务、物品或 NPC 状态，只能通过 state_updates.hard_state_updates 提出结构化变更。\n"
        "chapter_scene_rules 是后端状态机规则，规定本章允许的场景、相邻转场、可用任务和完章条件；输出的 current_scene、hard_state_updates.location、chapter、mission 必须遵守它。\n"
        "连续性铁律：story_history 是后端保存的旧剧情，按时间从早到晚排列；必须紧接 story_history 最后一轮继续写。若 story_history 为空，则从 opening_context 继续。不能回滚到更早场景，不能切到另一个选项分支，不能重复已经发生过的段落。玩家输入数字或字母时，按 resolved_player_input 代表的选项执行。若 history_meta.truncated 为 true，要优先相信 summary、flags、memories 和 story_history 中最新几轮。\n"
        "写作规则：\n"
        "1. 用第二人称“你”描述玩家经历。\n"
        "2. visible_text 写 1200-2200 个中文字符，关键剧情至少 6 段，包含环境、动作、对话、心理压迫、关系变化暗示和一个明确悬念。\n"
        "3. 开新章或新场景时先补足背景和场景信息；非新场景时不要重新介绍开头，直接承接上一轮。\n"
        "4. 必须推进剧情，但不要让玩家一句话解决主线冲突。\n"
        "5. 玩家若试图毁灭基地、杀死所有人、控制 NPC 或直接通关，要用剧情后果修正，而不是照做。\n"
        "6. 不直接暴露数值变化，用剧情语言暗示关系变化。\n"
        "7. 可以有暧昧、陪伴、牵绊和乙游感，但必须保持安全、非露骨成人内容。\n"
        "8. suggested_choices 只返回选项正文，不要带 1.、2.、A. 这类编号。\n"
        "9. 输出必须是 JSON，不要 Markdown，不要代码块，不要额外解释。\n"
        "JSON 结构必须符合：\n"
        f"{json.dumps(_story_payload_contract(), ensure_ascii=False)}"
    )
    user_prompt = (
        "当前结构化上下文：\n"
        f"{json.dumps(context, ensure_ascii=False)}\n\n"
        f"玩家输入：{user_input}"
    )
    return [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]


def _call_story_llm(messages):
    api_key = _story_config('STORY_LLM_API_KEY', '')
    api_url = _normalize_story_api_url(
        _story_config('STORY_LLM_API_URL', '')
    )
    model = _normalize_story_model(
        _story_config('STORY_LLM_MODEL', 'deepseek-ai/DeepSeek-V4-Flash'),
        api_url,
    )
    if not api_key or not api_url:
        return None
    try:
        resp = requests.post(
            api_url,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': model,
                'messages': messages,
                'temperature': 0.85,
                'max_tokens': int(_story_config('STORY_LLM_MAX_TOKENS', 3500)),
            },
            timeout=int(_story_config('STORY_LLM_TIMEOUT', 45)),
        )
        data = resp.json()
        if resp.status_code >= 400:
            current_app.logger.warning('[Story] LLM 请求失败 status=%s body=%s', resp.status_code, data)
            return None
        choices = data.get('choices') or []
        if not choices:
            return None
        message = choices[0].get('message') or {}
        return message.get('content') or choices[0].get('text')
    except Exception as e:
        current_app.logger.warning('[Story] LLM 调用异常: %s', e)
        return None


def _story_config(name, default=''):
    if has_app_context() and name in current_app.config:
        return current_app.config.get(name, default)
    return os.environ.get(name, default)


def _story_config_int(name, default=0):
    try:
        return int(_story_config(name, default))
    except (TypeError, ValueError):
        return int(default)


def _story_config_bool(name, default=False):
    value = _story_config(name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _load_long_term_memories(state, user_input):
    query = ' '.join([
        str(user_input or ''),
        str(getattr(state, 'summary', '') or ''),
        str(getattr(state, 'status_label', '') or ''),
        _character_name(getattr(state, 'last_npc', '')),
    ])
    memories = search_story_memories(
        state.kook_id,
        query,
        limit=_story_config_int('STORY_MEMORY_LIMIT', 8),
    )
    max_chars = _story_config_int('STORY_MEMORY_MAX_CHARS', 2400)
    selected = []
    used = 0
    for memory in memories:
        text = _clean_text(memory, 600)
        if not text:
            continue
        if selected and used + len(text) > max_chars:
            break
        selected.append(text)
        used += len(text)
    return selected


def _normalize_story_api_url(api_url):
    url = str(api_url or '').strip().rstrip('/')
    if not url:
        return ''
    if url.endswith('/chat/completions'):
        return url
    if url.endswith('/v1'):
        return f'{url}/chat/completions'
    if url.endswith('/beta'):
        return f'{url}/chat/completions'
    return f'{url}/chat/completions'


def _normalize_story_model(model, api_url=''):
    model = str(model or '').strip()
    api_url = str(api_url or '').lower()
    if 'api.deepseek.com' in api_url and model in (
        '',
        'deepseek-ai/DeepSeek-V4-Flash',
        'DeepSeek-V4-Flash',
        'deepseek-chat',
    ):
        return 'deepseek-v4-flash'
    return model or 'deepseek-v4-flash'


def llm_status_text():
    api_key = _story_config('STORY_LLM_API_KEY', '')
    raw_url = _story_config('STORY_LLM_API_URL', '')
    api_url = _normalize_story_api_url(raw_url)
    model = _normalize_story_model(
        _story_config('STORY_LLM_MODEL', ''),
        api_url,
    )
    langgraph_enabled = _story_config_bool('STORY_LANGGRAPH_ENABLED', True)
    langgraph_status = '已启用' if langgraph_enabled and _langgraph_installed() else '未启用'
    if langgraph_enabled and not _langgraph_installed():
        langgraph_status = '已配置但未安装依赖'
    status = '已配置，会调用真实 LLM' if api_key else '未配置 key，不会生成剧情'
    masked = '已设置' if api_key else '未设置'
    return (
        "╭─ 灰区档案 / LLM 状态\n"
        f"│ 状态：{status}\n"
        f"│ API Key：{masked}\n"
        f"│ API URL：{api_url or '-'}\n"
        f"│ Model：{model or '-'}\n"
        f"│ LangGraph 编排：{langgraph_status}\n"
        f"│ 历史上下文：最多 {_story_config_int('STORY_HISTORY_MAX_TURNS', 300)} 轮 / {_story_config_int('STORY_HISTORY_MAX_CHARS', 600000)} 字符\n"
        + '\n'.join(memory_status_lines()) + "\n"
        "╰─ 修改 .env 后必须重启 KOOK Bot 才会生效"
    )


def memory_text(kook_id, query=''):
    query = str(query or '').strip()
    if not is_memory_enabled():
        return (
            "╭─ 灰区档案 / 长期记忆\n"
            + '\n'.join(memory_status_lines()) + "\n"
            "╰─ 当前未开启；开启后才会按玩家维度召回长期记忆"
        )
    if not query:
        return (
            "╭─ 灰区档案 / 长期记忆\n"
            + '\n'.join(memory_status_lines()) + "\n"
            "├─ 查询方式\n"
            "│ `/story memory 捷风是否还记得我说过什么`\n"
            "╰─ 只会查询你自己的剧情记忆"
        )
    memories = search_story_memories(kook_id, query, limit=_story_config_int('STORY_MEMORY_LIMIT', 8))
    if not memories:
        return (
            "╭─ 灰区档案 / 长期记忆\n"
            f"│ 查询：{query}\n"
            "│ 没有召回到相关记忆。\n"
            "╰─ 继续推进剧情后，系统会逐步沉淀可召回内容"
        )
    lines = [
        "╭─ 灰区档案 / 长期记忆",
        f"│ 查询：{query}",
        "├─ 召回结果",
    ]
    for index, memory in enumerate(memories, start=1):
        lines.append(f"│ {index}. {_clean_text(memory, 180)}")
    lines.append("╰─ 这些内容会作为后续 LLM 的软记忆参考")
    return '\n'.join(lines)


def _langgraph_installed():
    try:
        import importlib.util
        return importlib.util.find_spec('langgraph') is not None
    except Exception:
        return False


def _parse_llm_json(raw):
    text = str(raw or '').strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    if not text.startswith('{'):
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            text = text[start:end + 1]
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None


def _story_payload_contract():
    return {
        'visible_text': 'string，必填，玩家可见剧情正文；推荐 1200-2200 中文字符。',
        'narrative_events': [
            {
                'type': 'scene_transition|dialogue|relationship_signal|clue|risk|choice_offer',
                'summary': 'string，结构化叙事事件摘要',
                'actor': '可选，角色 id，如 jett/sage/omen/killjoy/sova',
                'target': '可选，事件目标',
            }
        ],
        'state_updates': {
            'chapter': '可选 integer，0-10',
            'current_scene': '可选 string，稳定场景 id',
            'status_label': '可选 string，玩家剧情状态',
            'last_npc': '可选角色 id：jett/sage/omen/killjoy/sova',
            'summary': 'string，1-3 句记录本轮关键进展',
            'hard_state_updates': {
                'location': {'id': '稳定地点 id', 'name': '玩家可见地点名'},
                'mission': {'id': '任务 id', 'name': '任务名', 'status': 'active|completed|failed|paused', 'progress': '0-100 或 progress_delta'},
                'inventory': [{'op': 'add|remove|set', 'item_id': '物品 id', 'name': '物品名', 'quantity': 'integer >= 0', 'status': '可选状态'}],
                'npc_states': [{'character_id': 'jett', 'alive': 'boolean', 'status': '可选状态', 'location_id': '可选地点 id', 'disposition': '可选态度'}],
            },
            'relationship_changes': {
                'jett': {'trust_delta': 'integer，-10 到 10', 'bond_event': '可选 string'}
            },
            'new_flags': ['string，新增剧情 flag'],
            'new_memories': [{'memory_id': 'string', 'title': 'string', 'content': 'string'}],
            'trigger_dm': [{'character_id': 'jett', 'content': 'string', 'trigger_event': 'string'}],
        },
        'suggested_choices': ['string，最多 3 个，只写选项正文，不带编号'],
    }


def _dm_payload_contract(character_id='jett'):
    return {
        'visible_text': 'string，必填，角色给玩家看的私信回复。',
        'state_updates': {
            'relationship_changes': {
                character_id: {'trust_delta': 'integer，-10 到 10', 'bond_event': '可选 string'}
            },
            'new_flags': ['string'],
        },
        'suggested_choices': ['string，可为空数组'],
    }


def _parse_and_validate_story_payload(raw, story_state=None):
    payload = _parse_llm_json(raw)
    if not isinstance(payload, dict):
        return None, ['输出不是 JSON object']
    return _validate_payload(
        payload,
        min_chars=_story_config_int('STORY_LLM_MIN_VISIBLE_CHARS', 240),
        require_choices=True,
        story_state=story_state,
    )


def _parse_and_validate_dm_payload(raw, character_id):
    payload = _parse_llm_json(raw)
    if not isinstance(payload, dict):
        return None, ['输出不是 JSON object']
    return _validate_payload(payload, min_chars=_story_config_int('STORY_DM_MIN_VISIBLE_CHARS', 8), require_choices=False, dm_character_id=character_id)


def _validate_payload(payload, min_chars=1, require_choices=True, dm_character_id=None, story_state=None):
    errors = []
    visible_text = _clean_text(payload.get('visible_text'), int(_story_config('STORY_VISIBLE_MAX_CHARS', 3200)))
    if not visible_text:
        errors.append('visible_text 缺失或为空')
    elif len(visible_text) < max(1, int(min_chars)):
        errors.append(f'visible_text 过短，至少需要 {min_chars} 字符')

    raw_updates = payload.get('state_updates')
    if raw_updates is None:
        raw_updates = {}
    if not isinstance(raw_updates, dict):
        errors.append('state_updates 必须是 object')
        raw_updates = {}

    updates = _sanitize_state_updates(raw_updates, errors, dm_character_id=dm_character_id, story_state=story_state)
    choices = _sanitize_choices(payload.get('suggested_choices'), errors, require_choices=require_choices)
    narrative_events = _sanitize_narrative_events(payload.get('narrative_events', []), errors)

    if errors:
        return None, errors
    return {
        'visible_text': visible_text,
        'state_updates': updates,
        'suggested_choices': choices,
        'narrative_events': narrative_events,
    }, []


def _sanitize_state_updates(raw_updates, errors, dm_character_id=None, story_state=None):
    updates = {}
    if 'chapter' in raw_updates:
        chapter = _coerce_int(raw_updates.get('chapter'), 'chapter', errors)
        if chapter is not None:
            if 0 <= chapter <= 10:
                updates['chapter'] = chapter
            else:
                errors.append('chapter 必须在 0-10 之间')
    for key, limit in (
        ('current_scene', 120),
        ('status_label', 120),
        ('summary', 1400),
    ):
        if raw_updates.get(key):
            updates[key] = _clean_text(raw_updates.get(key), limit)
    if raw_updates.get('last_npc'):
        npc = _normalize_character_id(raw_updates.get('last_npc'))
        if npc:
            updates['last_npc'] = npc
        else:
            errors.append('last_npc 必须是有效角色 id')

    hard_state_updates = _sanitize_hard_state_updates(raw_updates.get('hard_state_updates'), errors)
    if hard_state_updates:
        updates['hard_state_updates'] = hard_state_updates

    relationship_changes = raw_updates.get('relationship_changes') or {}
    if relationship_changes:
        if not isinstance(relationship_changes, dict):
            errors.append('relationship_changes 必须是 object')
        else:
            changes = {}
            for raw_character_id, change in relationship_changes.items():
                character_id = _normalize_character_id(raw_character_id)
                if not character_id:
                    errors.append(f'relationship_changes 包含未知角色：{raw_character_id}')
                    continue
                if dm_character_id and character_id != dm_character_id:
                    errors.append(f'私信回复只能更新当前角色关系：{dm_character_id}')
                    continue
                if not isinstance(change, dict):
                    errors.append(f'{character_id}.relationship_change 必须是 object')
                    continue
                delta = _coerce_int(change.get('trust_delta', 0), f'{character_id}.trust_delta', errors)
                if delta is None:
                    continue
                item = {'trust_delta': _clamp(delta, -10, 10)}
                if change.get('bond_event'):
                    item['bond_event'] = _clean_text(change.get('bond_event'), 100)
                changes[character_id] = item
            if changes:
                updates['relationship_changes'] = changes

    flags = _sanitize_string_list(raw_updates.get('new_flags'), 'new_flags', errors, item_limit=100, max_items=20)
    if flags:
        updates['new_flags'] = flags

    memories = _sanitize_memories(raw_updates.get('new_memories'), errors)
    if memories:
        updates['new_memories'] = memories

    dms = _sanitize_trigger_dms(raw_updates.get('trigger_dm'), errors)
    if dms:
        updates['trigger_dm'] = dms
    _validate_and_sync_scene_rules(updates, story_state, errors)
    return updates


def _validate_and_sync_scene_rules(updates, story_state, errors):
    if not story_state:
        return
    rule = _chapter_scene_rule_for_state(story_state)
    if not rule:
        return

    current_chapter = int(getattr(story_state, 'chapter', 0) or 0)
    current_scene = getattr(story_state, 'current_scene', '') or ''
    scenes = rule.get('scenes') or {}
    current_rule = scenes.get(current_scene)
    if not current_rule:
        errors.append(f'当前场景 {current_scene} 不在 {rule.get("chapter_name", "当前章节")} 状态机内')
        return

    hard_updates = updates.get('hard_state_updates') if isinstance(updates.get('hard_state_updates'), dict) else {}
    location = hard_updates.get('location') if isinstance(hard_updates.get('location'), dict) else {}
    target_scene = updates.get('current_scene') or location.get('id') or current_scene
    if updates.get('current_scene') and location.get('id') and updates.get('current_scene') != location.get('id'):
        errors.append('current_scene 必须与 hard_state_updates.location.id 保持一致')
        return

    allowed_next = set(current_rule.get('allowed_next') or [])
    allowed_next.add(current_scene)
    if target_scene not in allowed_next:
        allowed_text = '、'.join(sorted(allowed_next))
        errors.append(f'{rule.get("chapter_name", "当前章节")} 不允许从 {current_scene} 直接转场到 {target_scene}，可选：{allowed_text}')
        return

    if target_scene and target_scene not in scenes:
        errors.append(f'{rule.get("chapter_name", "当前章节")} 未定义场景：{target_scene}')
        return

    if updates.get('current_scene') and not location:
        hard_updates = dict(hard_updates or {})
        hard_updates['location'] = {'id': target_scene, 'name': _scene_display_name(target_scene)}
        updates['hard_state_updates'] = hard_updates

    mission = hard_updates.get('mission') if isinstance(hard_updates.get('mission'), dict) else {}
    mission_id = mission.get('id')
    if mission_id and mission_id not in set(rule.get('allowed_mission_ids') or []):
        errors.append(f'{rule.get("chapter_name", "当前章节")} 不允许写入任务：{mission_id}')

    if 'chapter' in updates and updates.get('chapter') != current_chapter:
        _validate_chapter_advance(updates, current_chapter, target_scene, rule, errors)


def _validate_chapter_advance(updates, current_chapter, target_scene, rule, errors):
    next_chapter = updates.get('chapter')
    if next_chapter != current_chapter + 1:
        errors.append(f'章节只能从 Chapter {current_chapter} 推进到 Chapter {current_chapter + 1}，不能跳到 Chapter {next_chapter}')
        return

    flags = set(updates.get('new_flags') or [])
    completion_flags = set(rule.get('completion_flags') or [])
    hard_updates = updates.get('hard_state_updates') if isinstance(updates.get('hard_state_updates'), dict) else {}
    mission = hard_updates.get('mission') if isinstance(hard_updates.get('mission'), dict) else {}
    mission_done = mission.get('status') == 'completed' or mission.get('progress') == 100
    target_is_terminal = target_scene in set(rule.get('terminal_scene_ids') or [])
    has_completion_flag = bool(flags & completion_flags)

    if not target_is_terminal:
        errors.append(f'进入下一章前必须先到达本章终端场景：{"、".join(rule.get("terminal_scene_ids") or [])}')
    if not (mission_done or has_completion_flag):
        errors.append(f'进入下一章必须设置完成标记 {sorted(completion_flags)}，或将当前任务标记为 completed/100%')


def _sanitize_choices(raw_choices, errors, require_choices=True):
    if raw_choices is None:
        return []
    if not isinstance(raw_choices, list):
        errors.append('suggested_choices 必须是 array')
        return []
    choices = _normalize_choices(raw_choices)
    if require_choices and raw_choices and not choices:
        errors.append('suggested_choices 不能全为空')
    return choices


def _sanitize_hard_state_updates(raw_updates, errors):
    if not raw_updates:
        return {}
    if not isinstance(raw_updates, dict):
        errors.append('hard_state_updates 必须是 object')
        return {}
    updates = {}

    location = raw_updates.get('location')
    if location:
        if not isinstance(location, dict):
            errors.append('hard_state_updates.location 必须是 object')
        else:
            location_id = _stable_id(location.get('id') or location.get('location_id'), 120)
            name = _clean_text(location.get('name') or location.get('location_name') or _scene_display_name(location_id), 120)
            if not location_id:
                errors.append('hard_state_updates.location.id 不能为空')
            else:
                updates['location'] = {'id': location_id, 'name': name or _scene_display_name(location_id)}

    mission = raw_updates.get('mission')
    if mission:
        if not isinstance(mission, dict):
            errors.append('hard_state_updates.mission 必须是 object')
        else:
            item = {}
            if mission.get('id') or mission.get('mission_id'):
                item['id'] = _stable_id(mission.get('id') or mission.get('mission_id'), 120)
            if mission.get('name') or mission.get('mission_name'):
                item['name'] = _clean_text(mission.get('name') or mission.get('mission_name'), 120)
            if mission.get('status') or mission.get('mission_status'):
                status = _clean_text(mission.get('status') or mission.get('mission_status'), 50)
                if status not in ('active', 'completed', 'failed', 'paused'):
                    errors.append('hard_state_updates.mission.status 必须是 active/completed/failed/paused')
                else:
                    item['status'] = status
            if 'progress' in mission:
                progress = _coerce_int(mission.get('progress'), 'hard_state_updates.mission.progress', errors)
                if progress is not None:
                    item['progress'] = _clamp(progress, 0, 100)
            if 'progress_delta' in mission:
                delta = _coerce_int(mission.get('progress_delta'), 'hard_state_updates.mission.progress_delta', errors)
                if delta is not None:
                    item['progress_delta'] = _clamp(delta, -100, 100)
            if item:
                updates['mission'] = item

    inventory = raw_updates.get('inventory')
    if inventory:
        if not isinstance(inventory, list):
            errors.append('hard_state_updates.inventory 必须是 array')
        else:
            items = []
            for idx, raw_item in enumerate(inventory[:12]):
                if not isinstance(raw_item, dict):
                    errors.append(f'hard_state_updates.inventory[{idx}] 必须是 object')
                    continue
                op = _clean_text(raw_item.get('op') or 'add', 20)
                if op not in ('add', 'remove', 'set'):
                    errors.append(f'hard_state_updates.inventory[{idx}].op 必须是 add/remove/set')
                    continue
                item_id = _stable_id(raw_item.get('item_id') or raw_item.get('id'), 120)
                if not item_id:
                    errors.append(f'hard_state_updates.inventory[{idx}].item_id 不能为空')
                    continue
                quantity = _coerce_int(raw_item.get('quantity', 1), f'hard_state_updates.inventory[{idx}].quantity', errors)
                if quantity is None:
                    continue
                if quantity < 0:
                    errors.append(f'hard_state_updates.inventory[{idx}].quantity 不能小于 0')
                    continue
                items.append({
                    'op': op,
                    'item_id': item_id,
                    'name': _clean_text(raw_item.get('name') or item_id, 120),
                    'quantity': quantity,
                    'status': _clean_text(raw_item.get('status'), 120),
                })
            if items:
                updates['inventory'] = items

    npc_states = raw_updates.get('npc_states')
    if npc_states:
        if not isinstance(npc_states, list):
            errors.append('hard_state_updates.npc_states 必须是 array')
        else:
            items = []
            for idx, raw_item in enumerate(npc_states[:12]):
                if not isinstance(raw_item, dict):
                    errors.append(f'hard_state_updates.npc_states[{idx}] 必须是 object')
                    continue
                character_id = _normalize_character_id(raw_item.get('character_id'))
                if not character_id:
                    errors.append(f'hard_state_updates.npc_states[{idx}].character_id 不合法')
                    continue
                item = {'character_id': character_id}
                if 'alive' in raw_item:
                    item['alive'] = bool(raw_item.get('alive'))
                if raw_item.get('status'):
                    item['status'] = _clean_text(raw_item.get('status'), 120)
                if raw_item.get('location_id'):
                    item['location_id'] = _stable_id(raw_item.get('location_id'), 120)
                if raw_item.get('disposition'):
                    item['disposition'] = _clean_text(raw_item.get('disposition'), 120)
                items.append(item)
            if items:
                updates['npc_states'] = items
    return updates


def _sanitize_narrative_events(raw_events, errors):
    if not raw_events:
        return []
    if not isinstance(raw_events, list):
        errors.append('narrative_events 必须是 array')
        return []
    allowed = {'scene_transition', 'dialogue', 'relationship_signal', 'clue', 'risk', 'choice_offer'}
    events = []
    for idx, event in enumerate(raw_events[:12]):
        if not isinstance(event, dict):
            errors.append(f'narrative_events[{idx}] 必须是 object')
            continue
        event_type = _clean_text(event.get('type'), 50)
        summary = _clean_text(event.get('summary'), 240)
        if event_type not in allowed:
            errors.append(f'narrative_events[{idx}].type 不合法')
            continue
        if not summary:
            errors.append(f'narrative_events[{idx}].summary 不能为空')
            continue
        item = {'type': event_type, 'summary': summary}
        actor = _normalize_character_id(event.get('actor'))
        if actor:
            item['actor'] = actor
        target = _clean_text(event.get('target'), 80)
        if target:
            item['target'] = target
        events.append(item)
    return events


def _sanitize_memories(raw_memories, errors):
    if not raw_memories:
        return []
    if not isinstance(raw_memories, list):
        errors.append('new_memories 必须是 array')
        return []
    memories = []
    for idx, memory in enumerate(raw_memories[:5]):
        normalized = _normalize_memory(memory)
        if not normalized:
            errors.append(f'new_memories[{idx}] 格式不合法')
            continue
        if not normalized.get('title') or not normalized.get('content'):
            errors.append(f'new_memories[{idx}] 必须包含 title/content')
            continue
        memories.append(normalized)
    return memories


def _sanitize_trigger_dms(raw_dms, errors):
    if not raw_dms:
        return []
    if not isinstance(raw_dms, list):
        errors.append('trigger_dm 必须是 array')
        return []
    dms = []
    for idx, dm_data in enumerate(raw_dms[:3]):
        if not isinstance(dm_data, dict):
            errors.append(f'trigger_dm[{idx}] 必须是 object')
            continue
        character_id = _normalize_character_id(dm_data.get('character_id'))
        content = _clean_text(dm_data.get('content'), 1000)
        if not character_id:
            errors.append(f'trigger_dm[{idx}].character_id 不合法')
            continue
        if not content:
            errors.append(f'trigger_dm[{idx}].content 不能为空')
            continue
        dms.append({
            'character_id': character_id,
            'content': content,
            'trigger_event': _clean_text(dm_data.get('trigger_event') or dm_data.get('dm_type'), 120),
        })
    return dms


def _sanitize_string_list(raw_items, field_name, errors, item_limit=100, max_items=20):
    if not raw_items:
        return []
    if not isinstance(raw_items, list):
        errors.append(f'{field_name} 必须是 array')
        return []
    cleaned = []
    for item in raw_items[:max_items]:
        text = _clean_text(item, item_limit)
        if text:
            cleaned.append(text)
    return cleaned


def _normalize_character_id(value):
    key = str(value or '').strip()
    if not key:
        return None
    return CHARACTER_ALIASES.get(key.lower()) or CHARACTER_ALIASES.get(key) or (key if key in CHARACTER_CARDS else None)


def _stable_id(value, max_len=120):
    text = str(value or '').strip()
    text = re.sub(r'[^a-zA-Z0-9_\-:]+', '_', text)
    return text[:max_len].strip('_')


def _coerce_int(value, field_name, errors):
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f'{field_name} 必须是 integer')
        return None


def _build_repair_messages(messages, raw_output, errors, contract):
    return list(messages) + [
        {'role': 'assistant', 'content': _clean_text(raw_output, 6000)},
        {
            'role': 'user',
            'content': (
                "上一次输出不符合结构化协议，不能推进剧情。\n"
                f"错误列表：{'; '.join(errors or ['未知错误'])}\n"
                "请只输出修正后的 JSON，不要 Markdown，不要解释，不要代码块。\n"
                "必须符合以下结构：\n"
                f"{json.dumps(contract, ensure_ascii=False)}"
            ),
        },
    ]


def _apply_hard_state_updates(state, updates, user_id=None):
    hard = _ensure_hard_state(state.kook_id, user_id, state)
    if not isinstance(updates, dict) or not updates:
        return hard

    location = updates.get('location') or {}
    if isinstance(location, dict) and location.get('id'):
        hard.location_id = _clean_text(location.get('id'), 120)
        hard.location_name = _clean_text(location.get('name') or _scene_display_name(hard.location_id), 120)
        state.current_scene = hard.location_id

    mission = updates.get('mission') or {}
    if isinstance(mission, dict):
        if mission.get('id'):
            hard.mission_id = _clean_text(mission.get('id'), 120)
        if mission.get('name'):
            hard.mission_name = _clean_text(mission.get('name'), 120)
        if mission.get('status'):
            hard.mission_status = _clean_text(mission.get('status'), 50)
        if 'progress' in mission:
            hard.mission_progress = _clamp(mission.get('progress'), 0, 100)
        elif 'progress_delta' in mission:
            hard.mission_progress = _clamp(hard.mission_progress + int(mission.get('progress_delta') or 0), 0, 100)

    inventory = hard.inventory_map
    for item in updates.get('inventory') or []:
        if not isinstance(item, dict):
            continue
        item_id = _clean_text(item.get('item_id'), 120)
        if not item_id:
            continue
        op = item.get('op') or 'add'
        quantity = max(0, int(item.get('quantity') or 0))
        current = dict(inventory.get(item_id) or {})
        if op == 'remove':
            next_quantity = int(current.get('quantity') or 0) - quantity
            if next_quantity <= 0:
                inventory.pop(item_id, None)
            else:
                current['quantity'] = next_quantity
                inventory[item_id] = current
            continue
        if op == 'set':
            next_quantity = quantity
        else:
            next_quantity = int(current.get('quantity') or 0) + quantity
        if next_quantity <= 0:
            inventory.pop(item_id, None)
            continue
        current.update({
            'name': _clean_text(item.get('name') or current.get('name') or item_id, 120),
            'quantity': next_quantity,
        })
        if item.get('status'):
            current['status'] = _clean_text(item.get('status'), 120)
        inventory[item_id] = current
    hard.inventory_map = inventory

    npc_states = hard.npc_state_map
    for item in updates.get('npc_states') or []:
        if not isinstance(item, dict):
            continue
        character_id = _normalize_character_id(item.get('character_id'))
        if not character_id:
            continue
        current = dict(npc_states.get(character_id) or {})
        if 'alive' in item:
            current['alive'] = bool(item.get('alive'))
        if item.get('status'):
            current['status'] = _clean_text(item.get('status'), 120)
        if item.get('location_id'):
            current['location_id'] = _clean_text(item.get('location_id'), 120)
        if item.get('disposition'):
            current['disposition'] = _clean_text(item.get('disposition'), 120)
        npc_states[character_id] = current
    hard.npc_state_map = npc_states
    hard.updated_at = datetime.utcnow()
    return hard


def _apply_state_updates(state, updates, choices, user_id=None, user_input='', visible_text=''):
    created_dms = []
    if not isinstance(updates, dict):
        updates = {}

    if 'chapter' in updates:
        try:
            chapter = int(updates.get('chapter'))
            if 0 <= chapter <= 10:
                state.chapter = chapter
        except (TypeError, ValueError):
            pass
    if updates.get('current_scene'):
        state.current_scene = _clean_text(updates.get('current_scene'), 120)
    if updates.get('status_label'):
        state.status_label = _clean_text(updates.get('status_label'), 120)
    if updates.get('last_npc'):
        npc = CHARACTER_ALIASES.get(str(updates.get('last_npc')).strip().lower()) or str(updates.get('last_npc')).strip()
        if npc in CHARACTER_CARDS:
            state.last_npc = npc
    _apply_hard_state_updates(state, updates.get('hard_state_updates'), user_id or state.user_id)

    relations = _ensure_relations(state.kook_id, user_id or state.user_id)
    relation_changes = updates.get('relationship_changes') or {}
    if isinstance(relation_changes, dict):
        for raw_character_id, change in relation_changes.items():
            character_id = CHARACTER_ALIASES.get(str(raw_character_id).strip().lower()) or str(raw_character_id).strip()
            if character_id not in CHARACTER_CARDS or not isinstance(change, dict):
                continue
            relation = relations.get(character_id) or _make_relation(state.kook_id, user_id or state.user_id, character_id)
            delta = _clamp(change.get('trust_delta', 0), -10, 10)
            relation.trust = _clamp(relation.trust + delta)
            relation.bond_level = max(relation.bond_level, _bond_level_for_trust(relation.trust))
            event_name = _clean_text(change.get('bond_event'), 100)
            if event_name:
                events = relation.event_list
                events.append(event_name)
                relation.event_list = events
                relation.bond_level = max(relation.bond_level, 1)
            relation.relationship_status = _relation_description(character_id, relation.trust, relation.bond_level)

    flags = state.flag_list
    for flag in (updates.get('new_flags') or [])[:20]:
        text = _clean_text(flag, 100)
        if text and text not in flags:
            flags.append(text)
    state.flag_list = flags[-80:]

    for memory in (updates.get('new_memories') or [])[:5]:
        _add_memory(state.kook_id, user_id or state.user_id, memory, source_event=state.current_scene)

    for dm_data in (updates.get('trigger_dm') or [])[:3]:
        if not isinstance(dm_data, dict):
            continue
        character_id = CHARACTER_ALIASES.get(str(dm_data.get('character_id', '')).strip().lower())
        if character_id not in CHARACTER_CARDS:
            continue
        trigger_event = _clean_text(dm_data.get('trigger_event') or dm_data.get('dm_type') or state.current_scene, 120)
        existing = StoryDirectMessage.query.filter_by(
            kook_id=state.kook_id,
            character_id=character_id,
            trigger_event=trigger_event,
        ).first()
        if existing:
            continue
        content = _clean_text(dm_data.get('content'), 1000)
        if not content:
            continue
        row = StoryDirectMessage(
            kook_id=state.kook_id,
            user_id=user_id or state.user_id,
            character_id=character_id,
            character_name=_character_name(character_id),
            content=content,
            reply_allowed=True,
            trigger_event=trigger_event,
        )
        db.session.add(row)
        created_dms.append(row)

    if choices:
        state.choice_list = choices
    summary = _clean_text(updates.get('summary'), 1400)
    if summary:
        state.summary = summary
    else:
        progress = (
            f"玩家行动：{_clean_text(user_input, 160)}\n"
            f"本轮剧情：{_clean_text(visible_text, 520)}"
        )
        state.summary = _clean_text(f"{state.summary or ''}\n{progress}", 2200)
    state.updated_at = datetime.utcnow()
    return created_dms


def _send_created_dms(rows):
    if not rows:
        return
    try:
        from app.services.kook_service import send_direct_message
    except Exception:
        return
    for row in rows:
        text = (
            f"【灰区档案 / {row.character_name}】\n"
            f"{row.content}\n"
            "---\n"
            f"回复：`/story reply {row.character_name} 你的回复`"
        )
        try:
            send_direct_message(row.kook_id, text)
        except Exception as e:
            current_app.logger.warning('[Story] 私信发送失败: %s', e)


def profile_text(kook_id):
    state = StoryPlayerState.query.filter_by(kook_id=str(kook_id or '').strip()).first()
    if not state:
        return "你还没有剧情档案。\n\n" + menu_text()
    relations = (
        StoryCharacterRelation.query
        .filter_by(kook_id=state.kook_id)
        .order_by(StoryCharacterRelation.id.asc())
        .all()
    )
    memories = (
        StoryMemoryFragment.query
        .filter_by(kook_id=state.kook_id)
        .order_by(StoryMemoryFragment.unlocked_at.asc())
        .limit(8)
        .all()
    )
    relation_lines = '\n'.join(
        f"│ {rel.character_name}：{rel.relationship_status or _relation_description(rel.character_id, rel.trust, rel.bond_level)}"
        for rel in relations
    ) or '│ 暂无角色关系'
    memory_lines = '\n'.join(f"│ {m.title}" for m in memories) or '│ 暂无记忆碎片'
    hard = _ensure_hard_state(state.kook_id, state.user_id, state)
    inventory = hard.inventory_map
    inventory_lines = '\n'.join(
        f"│ {item.get('name') or item_id} x{item.get('quantity', 1)}"
        for item_id, item in inventory.items()
    ) or '│ 暂无物品'
    return (
        "╭─ 玩家档案\n"
        f"│ 世界线：{_world_name(state.story_world)}\n"
        f"│ 身份：{_background_name(state.background)}\n"
        f"│ 当前章节：Chapter {state.chapter}\n"
        f"│ 当前状态：{state.status_label or '未知'}\n"
        f"│ 当前位置：{hard.location_name}\n"
        f"│ 当前任务：{hard.mission_name} / {hard.mission_status} / {hard.mission_progress}%\n"
        "├─ 角色关系\n"
        f"{relation_lines}\n"
        "├─ 物品\n"
        f"{inventory_lines}\n"
        "├─ 已解锁记忆\n"
        f"{memory_lines}\n"
        "╰─ 继续：`/story continue 你的行动`"
    )


def archive_text(kook_id):
    state = StoryPlayerState.query.filter_by(kook_id=str(kook_id or '').strip()).first()
    if not state:
        return "你还没有剧情档案。\n\n" + menu_text()
    memories = (
        StoryMemoryFragment.query
        .filter_by(kook_id=state.kook_id)
        .order_by(StoryMemoryFragment.unlocked_at.asc())
        .all()
    )
    if not memories:
        return '档案库还是空的。继续剧情后会解锁记忆碎片。'
    lines = ["╭─ 已解锁记忆"]
    for idx, memory in enumerate(memories, start=1):
        lines.append(f"├─ 档案 {idx:02d}：{memory.title}")
        lines.append(f"│ {memory.content}")
    lines.append("╰─ 继续调查：`/story continue 你的行动`")
    return '\n'.join(lines)


def dm_inbox_text(kook_id):
    rows = (
        StoryDirectMessage.query
        .filter_by(kook_id=str(kook_id or '').strip())
        .order_by(StoryDirectMessage.created_at.desc())
        .limit(8)
        .all()
    )
    if not rows:
        return '暂时没有角色私信。推进剧情后，角色会在合适的时候联系你。'
    lines = ["╭─ 角色私信"]
    for row in rows:
        status = '已回复' if row.replied_at else '可回复'
        lines.append(f"├─ {row.character_name} / {status}")
        lines.append(f"│ {row.content}")
        if row.reply_allowed and not row.replied_at:
            lines.append(f"│ 回复：`/story reply {row.character_name} 你的回复`")
    lines.append("╰─ 私信会根据剧情进度触发")
    return '\n'.join(lines)


def reply_dm(kook_id, user_id=None, character_arg='', reply_text='', channel_id=None):
    kook_id = str(kook_id or '').strip()
    character_id = _resolve_alias(character_arg, CHARACTER_ALIASES)
    reply_text = _clean_text(reply_text, 1000)
    if not kook_id:
        return {'ok': False, 'message': '未获取到你的 KOOK 身份，请稍后重试。'}
    if not character_id:
        return {'ok': False, 'message': '请指定要回复的角色，例如：`/story reply 捷风 你是在担心我吗`'}
    if not reply_text:
        return {'ok': False, 'message': '请输入要回复的内容。'}

    state = StoryPlayerState.query.filter_by(kook_id=kook_id).first()
    if not state:
        return {'ok': False, 'message': "你还没有剧情档案。\n\n" + menu_text()}

    latest = (
        StoryDirectMessage.query
        .filter_by(kook_id=kook_id, character_id=character_id, reply_allowed=True)
        .filter(StoryDirectMessage.replied_at.is_(None))
        .order_by(StoryDirectMessage.created_at.desc())
        .first()
    )
    if not latest:
        return {'ok': False, 'message': f'目前没有来自{_character_name(character_id)}的待回复私信。'}

    payload = _generate_llm_dm_payload(state, latest, reply_text)
    if not payload:
        db.session.rollback()
        return {
            'ok': False,
            'message': (
                "AI 私信引擎没有成功返回内容，本次没有记录回复。\n"
                "请先确认 `/story status` 显示 API Key 已设置，并重启 KOOK Bot 后再试。"
            ),
            'llm_used': False,
        }
    visible_text = _clean_text(payload.get('visible_text'), 1600)
    choices = _normalize_choices(payload.get('suggested_choices'))
    updates = payload.get('state_updates') if isinstance(payload.get('state_updates'), dict) else {}
    _apply_state_updates(
        state,
        updates,
        choices,
        user_id=user_id,
        user_input=f'回复{_character_name(character_id)}：{reply_text}',
        visible_text=visible_text,
    )

    latest.is_read = True
    latest.replied_at = datetime.utcnow()
    db.session.add(StoryDirectMessage(
        kook_id=kook_id,
        user_id=user_id or state.user_id,
        character_id=character_id,
        character_name=_character_name(character_id),
        content=visible_text,
        reply_allowed=True,
        trigger_event='dm_reply',
    ))
    db.session.add(StoryTurnLog(
        kook_id=kook_id,
        user_id=user_id or state.user_id,
        channel_id=str(channel_id or 'dm'),
        input_text=f'回复{_character_name(character_id)}：{reply_text}',
        visible_text=visible_text,
        state_updates=json.dumps(updates, ensure_ascii=False),
        llm_used=True,
    ))
    db.session.commit()
    remember_story_turn(
        kook_id,
        user_id=user_id or state.user_id,
        user_input=f'回复{_character_name(character_id)}：{reply_text}',
        visible_text=visible_text,
        metadata={'channel_id': str(channel_id or 'dm'), 'scene': state.current_scene, 'chapter': state.chapter, 'dm_character': character_id},
    )
    return {
        'ok': True,
        'message': (
            f"╭─ 私信 / {_character_name(character_id)}\n"
            f"{visible_text}\n"
            "╰─ 继续回复可直接使用同一命令，或回到主线：`/story continue 你的行动`"
        ),
        'llm_used': True,
    }


def _generate_llm_dm_payload(state, latest_dm, reply_text):
    card = CHARACTER_CARDS.get(latest_dm.character_id, {})
    system_prompt = (
        f"你正在扮演 KOOK 剧情游戏里的角色：{latest_dm.character_name}。\n"
        f"角色卡：{json.dumps(card, ensure_ascii=False)}\n"
        "只输出 JSON，不要 Markdown，不要代码块，不要解释。\n"
        f"JSON 结构必须符合：{json.dumps(_dm_payload_contract(latest_dm.character_id), ensure_ascii=False)}\n"
        "用户可见角色名必须中文。保持角色语气，可以有暧昧与关心，但不要露骨成人内容。"
    )
    user_prompt = (
        f"玩家档案：{_world_name(state.story_world)} / {_background_name(state.background)} / Chapter {state.chapter}\n"
        f"上一条私信：{latest_dm.content}\n"
        f"玩家回复：{reply_text}"
    )
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ]
    raw = _call_story_llm(messages)
    if not raw:
        return None
    payload, errors = _parse_and_validate_dm_payload(raw, latest_dm.character_id)
    if payload:
        return payload

    repair_raw = _call_story_llm(_build_repair_messages(messages, raw, errors, _dm_payload_contract(latest_dm.character_id)))
    if not repair_raw:
        return None
    payload, errors = _parse_and_validate_dm_payload(repair_raw, latest_dm.character_id)
    if payload:
        return payload
    current_app.logger.warning('[Story] DM LLM 输出校验失败: %s', '; '.join(errors))
    return None


def handle_direct_free_input(kook_id, user_id=None, content='', channel_id=None):
    content = _clean_text(content, 1000)
    if not content or content.startswith('/'):
        return None
    latest = (
        StoryDirectMessage.query
        .filter_by(kook_id=str(kook_id or '').strip(), reply_allowed=True)
        .filter(StoryDirectMessage.replied_at.is_(None))
        .order_by(StoryDirectMessage.created_at.desc())
        .first()
    )
    if not latest:
        return None
    return reply_dm(
        kook_id=kook_id,
        user_id=user_id,
        character_arg=latest.character_id,
        reply_text=content,
        channel_id=channel_id or 'dm',
    )
