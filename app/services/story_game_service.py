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

import requests
from flask import current_app, has_app_context

from app.extensions import db
from app.models.story_game import (
    StoryCharacterRelation,
    StoryDirectMessage,
    StoryMemoryFragment,
    StoryPlayerState,
    StoryTurnLog,
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
    kook_id = str(kook_id or '').strip()
    user_input = _clean_text(user_input, 1000)
    if not kook_id:
        return {'ok': False, 'message': '未获取到你的 KOOK 身份，请稍后重试。'}
    if not user_input:
        return {'ok': False, 'message': '请输入你的行动，例如：`/story continue 我举起手，说我不记得自己是谁`'}

    state = StoryPlayerState.query.filter_by(kook_id=kook_id).first()
    if not state:
        return {'ok': False, 'message': "你还没有剧情档案。\n\n" + menu_text()}
    if user_id and state.user_id != user_id:
        state.user_id = user_id

    payload = _generate_llm_story_payload(state, user_input)
    llm_used = payload is not None
    if not payload:
        payload = _fallback_story_payload(state, user_input)

    visible_text = _clean_text(payload.get('visible_text'), 1800)
    choices = _normalize_choices(payload.get('suggested_choices'))
    updates = payload.get('state_updates') if isinstance(payload.get('state_updates'), dict) else {}
    created_dms = _apply_state_updates(state, updates, choices, user_id=user_id)

    db.session.add(StoryTurnLog(
        kook_id=kook_id,
        user_id=user_id,
        channel_id=str(channel_id or ''),
        input_text=user_input,
        visible_text=visible_text,
        state_updates=json.dumps(updates, ensure_ascii=False),
        llm_used=llm_used,
    ))
    db.session.commit()
    _send_created_dms(created_dms)

    return {
        'ok': True,
        'message': _format_story_response(visible_text, choices),
        'llm_used': llm_used,
    }


def _normalize_choices(choices):
    if not isinstance(choices, list):
        return []
    cleaned = []
    for choice in choices[:3]:
        text = _clean_text(choice, 80)
        if text:
            cleaned.append(text)
    return cleaned


def _format_story_response(visible_text, choices):
    lines = ["╭─ 灰区档案", visible_text.strip()]
    if choices:
        lines.append("├─ 可选行动")
        for idx, choice in enumerate(choices, start=1):
            lines.append(f"{idx}. {choice}")
    lines.append("╰─ 继续自由输入：`/story continue 你的行动`")
    return '\n'.join(lines)


def _generate_llm_story_payload(state, user_input):
    raw = _call_story_llm(_build_story_messages(state, user_input))
    if not raw:
        return None
    payload = _parse_llm_json(raw)
    if not isinstance(payload, dict) or not _clean_text(payload.get('visible_text')):
        return None
    return payload


def _build_story_messages(state, user_input):
    relations = StoryCharacterRelation.query.filter_by(kook_id=state.kook_id).all()
    memories = (
        StoryMemoryFragment.query
        .filter_by(kook_id=state.kook_id)
        .order_by(StoryMemoryFragment.unlocked_at.desc())
        .limit(8)
        .all()
    )
    context = {
        'story_world': _world_name(state.story_world),
        'background': _background_name(state.background),
        'chapter': state.chapter,
        'current_scene': state.current_scene,
        'status_label': state.status_label,
        'last_npc': _character_name(state.last_npc),
        'flags': state.flag_list[-20:],
        'summary': state.summary,
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
        "写作规则：\n"
        "1. 用第二人称“你”描述玩家经历。\n"
        "2. 保持电影感、悬疑感和角色羁绊，不要写成说明书。\n"
        "3. 单次 visible_text 控制在 1000 个中文字符以内。\n"
        "4. 必须推进剧情，但不要让玩家一句话解决主线冲突。\n"
        "5. 玩家若试图毁灭基地、杀死所有人、控制 NPC 或直接通关，要用剧情后果修正，而不是照做。\n"
        "6. 不直接暴露数值变化，用剧情语言暗示关系变化。\n"
        "7. 可以有暧昧、陪伴、牵绊和乙游感，但必须保持安全、非露骨成人内容。\n"
        "8. 输出必须是 JSON，不要 Markdown，不要代码块，不要额外解释。\n"
        "JSON 结构：{\"visible_text\":\"...\",\"state_updates\":{\"chapter\":0,\"current_scene\":\"...\",\"status_label\":\"...\",\"last_npc\":\"jett\",\"relationship_changes\":{\"jett\":{\"trust_delta\":2,\"bond_event\":\"temporary_alliance\"}},\"new_flags\":[\"...\"],\"new_memories\":[{\"memory_id\":\"...\",\"title\":\"...\",\"content\":\"...\"}],\"trigger_dm\":[{\"character_id\":\"jett\",\"content\":\"...\",\"trigger_event\":\"...\"}]},\"suggested_choices\":[\"...\",\"...\",\"...\"]}"
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
                'max_tokens': 1800,
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
    if 'api.deepseek.com' in api_url and model in ('', 'deepseek-ai/DeepSeek-V4-Flash', 'DeepSeek-V4-Flash'):
        return 'deepseek-chat'
    return model or 'deepseek-chat'


def llm_status_text():
    api_key = _story_config('STORY_LLM_API_KEY', '')
    raw_url = _story_config('STORY_LLM_API_URL', '')
    api_url = _normalize_story_api_url(raw_url)
    model = _normalize_story_model(
        _story_config('STORY_LLM_MODEL', ''),
        api_url,
    )
    status = '已配置，会调用真实 LLM' if api_key else '未配置 key，会使用本地 fallback'
    masked = '已设置' if api_key else '未设置'
    return (
        "╭─ 灰区档案 / LLM 状态\n"
        f"│ 状态：{status}\n"
        f"│ API Key：{masked}\n"
        f"│ API URL：{api_url or '-'}\n"
        f"│ Model：{model or '-'}\n"
        "╰─ 修改 .env 后需要重启 KOOK Bot 才会生效"
    )


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


def _fallback_story_payload(state, user_input):
    reckless = bool(re.search(r'(杀死所有|摧毁|毁灭|直接通关|控制所有|游戏结束)', user_input))
    if reckless:
        return {
            'visible_text': (
                "你冲向控制台的瞬间，封锁门比你更快落下。红色警报覆盖整条训练走廊，"
                "基地 AI 的声音忽然变得平静：“异常目标攻击意图确认。”\n\n"
                "捷风从侧面拽住你的衣领，把你按回掩体后方。她的语气比枪口更冷。\n\n"
                "“你是想活下去，还是想让这里所有人陪你一起死？”\n\n"
                "你的冲动没有解决问题，反而让基地进入更高级别戒备。可也正因为这一瞬间，"
                "你看见控制台闪过一行被删除的记录：编号 07，回收失败次数：6。"
            ),
            'state_updates': {
                'chapter': state.chapter,
                'current_scene': 'escape_corridor_alert',
                'status_label': '高危异常目标',
                'last_npc': 'jett',
                'relationship_changes': {'jett': {'trust_delta': -2, 'bond_event': 'reckless_alert'}},
                'new_flags': ['reckless_alert_raised', 'memory_07_failed_recovery_seen'],
                'new_memories': [{
                    'memory_id': 'memory_02_failed_recovery',
                    'title': '第七次回收',
                    'content': '控制台短暂闪过记录：编号 07 并不是第一次被回收，前六次都以失败告终。',
                }],
                'trigger_dm': [],
            },
            'suggested_choices': ['向捷风道歉并冷静下来', '询问回收失败次数是什么意思', '寻找另一条离开训练室的路'],
        }

    dm_needed = 'jett_training_invite_sent' not in state.flag_list
    trigger_dm = []
    if dm_needed:
        trigger_dm.append({
            'character_id': 'jett',
            'content': '明天训练室，别迟到。\n还有，今天那一下不算你赢。我还有很多问题要问你。',
            'trigger_event': 'chapter_0_training_invite',
        })
    return {
        'visible_text': (
            "你没有放下手，但也没有后退。\n\n"
            "“我不记得自己是谁。”你听见自己的声音在训练室里发哑，“但我记得有人告诉我，不要相信这里的 AI。”\n\n"
            "捷风的枪口没有移开，指节却明显收紧了一下。广播仍在倒计时，门外有机械锁逐层解开的声音。"
            "她盯着你，像是在判断你是陷阱、幸存者，还是某个她不愿承认的旧答案。\n\n"
            "“很好。”她低声说，“那你最好现在就证明自己不是麻烦。”\n\n"
            "她一把扯开侧门，把一只备用通讯器丢给你。走廊尽头的红灯亮起，基地 AI 正在重新计算你的位置。"
        ),
        'state_updates': {
            'chapter': 0,
            'current_scene': 'escape_corridor',
            'status_label': '临时合作观察对象',
            'last_npc': 'jett',
            'relationship_changes': {'jett': {'trust_delta': 3, 'bond_event': 'temporary_alliance'}},
            'new_flags': ['told_jett_ai_warning', 'jett_temporarily_sides_with_player', 'jett_training_invite_sent'],
            'new_memories': [DEFAULT_MEMORY_07],
            'trigger_dm': trigger_dm,
        },
        'suggested_choices': ['跟随捷风离开训练室', '追问她是否认识你', '尝试监听基地 AI 的频道'],
    }


def _apply_state_updates(state, updates, choices, user_id=None):
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
        content = _clean_text(dm_data.get('content') or _default_dm_content(character_id, trigger_event), 1000)
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
    summary = _clean_text(updates.get('summary'), 1200)
    if summary:
        state.summary = summary
    else:
        state.summary = _clean_text(f"{state.summary or ''}\n最新进展：{state.status_label}，场景转入 {state.current_scene}。", 1500)
    state.updated_at = datetime.utcnow()
    return created_dms


def _default_dm_content(character_id, trigger_event):
    if character_id == 'jett':
        return '明天训练室，别迟到。\n还有，别以为今天那一下算你赢。'
    if character_id == 'sage':
        return '你今天看起来很累。如果又做噩梦，可以来医疗室。我会留一盏灯。'
    if character_id == 'omen':
        return '他们删除了你的名字。但影子记得。'
    if character_id == 'killjoy':
        return '我查了一下你的档案。好消息：你确实存在。坏消息：系统不承认你存在。'
    if character_id == 'sova':
        return '不要急着相信任何结论。痕迹不会说谎，人会。'
    return ''


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
    return (
        "╭─ 玩家档案\n"
        f"│ 世界线：{_world_name(state.story_world)}\n"
        f"│ 身份：{_background_name(state.background)}\n"
        f"│ 当前章节：Chapter {state.chapter}\n"
        f"│ 当前状态：{state.status_label or '未知'}\n"
        "├─ 角色关系\n"
        f"{relation_lines}\n"
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

    payload = _generate_llm_dm_payload(state, latest, reply_text) or _fallback_dm_payload(character_id, reply_text)
    llm_used = 'fallback' not in payload
    visible_text = _clean_text(payload.get('visible_text'), 1000)
    choices = _normalize_choices(payload.get('suggested_choices'))
    updates = payload.get('state_updates') if isinstance(payload.get('state_updates'), dict) else {}
    _apply_state_updates(state, updates, choices, user_id=user_id)

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
        llm_used=llm_used,
    ))
    db.session.commit()
    return {
        'ok': True,
        'message': (
            f"╭─ 私信 / {_character_name(character_id)}\n"
            f"{visible_text}\n"
            "╰─ 继续回复可直接使用同一命令，或回到主线：`/story continue 你的行动`"
        ),
        'llm_used': llm_used,
    }


def _generate_llm_dm_payload(state, latest_dm, reply_text):
    card = CHARACTER_CARDS.get(latest_dm.character_id, {})
    system_prompt = (
        f"你正在扮演 KOOK 剧情游戏里的角色：{latest_dm.character_name}。\n"
        f"角色卡：{json.dumps(card, ensure_ascii=False)}\n"
        "只输出 JSON：{\"visible_text\":\"角色给玩家的回复\",\"state_updates\":{\"relationship_changes\":{\"角色id\":{\"trust_delta\":1,\"bond_event\":\"...\"}},\"new_flags\":[]},\"suggested_choices\":[]}\n"
        "用户可见角色名必须中文。保持角色语气，可以有暧昧与关心，但不要露骨成人内容。"
    )
    user_prompt = (
        f"玩家档案：{_world_name(state.story_world)} / {_background_name(state.background)} / Chapter {state.chapter}\n"
        f"上一条私信：{latest_dm.content}\n"
        f"玩家回复：{reply_text}"
    )
    raw = _call_story_llm([
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': user_prompt},
    ])
    if not raw:
        return None
    payload = _parse_llm_json(raw)
    if not isinstance(payload, dict) or not _clean_text(payload.get('visible_text')):
        return None
    return payload


def _fallback_dm_payload(character_id, reply_text):
    if character_id == 'jett':
        visible = (
            "想多了。\n"
            "我只是懒得再给新人收拾烂摊子。\n\n"
            "……不过你要是真不来，我会去找你。别误会，是训练计划不能被你拖慢。"
        )
    elif character_id == 'sage':
        visible = "谢谢你愿意告诉我这些。你不需要一直表现得很坚强，至少在这里不用。"
    elif character_id == 'omen':
        visible = "你的声音穿过阴影。它没有回答所有问题，却证明你仍在这里。记住这一点。"
    elif character_id == 'killjoy':
        visible = "我把你的回复和异常日志对上了。好消息：你没疯。坏消息：系统可能真的在装作没听见。"
    elif character_id == 'sova':
        visible = "你做得不错。不是因为你没有害怕，而是因为你害怕了，还是继续走下去了。"
    else:
        visible = "对方短暂沉默了一会儿，像是在重新判断你们之间的距离。"
    return {
        'visible_text': visible,
        'state_updates': {
            'relationship_changes': {
                character_id: {'trust_delta': 2, 'bond_event': 'dm_reply_accepted'},
            },
            'new_flags': [f'{character_id}_dm_replied'],
        },
        'suggested_choices': [],
        'fallback': True,
    }


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
