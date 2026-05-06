"""KOOK 中文文本小游戏。"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import random
import re
import time


SESSION_TTL_SECONDS = 30 * 60

WORDS = (
    ('无畏契约', '战术射击游戏，也是店里常聊的项目'),
    ('爆头击杀', '一枪命中头部完成击杀'),
    ('残局处理', '人数劣势或时间紧张时的收尾能力'),
    ('高光时刻', '一局里最秀、最值得剪出来的瞬间'),
    ('经济管理', '买枪、存钱、起甲的资源安排'),
    ('排位连胜', '上分路上最快乐的连续胜利'),
    ('甜蜜双排', '两个人一起打排位'),
    ('极速转点', '从一个包点快速换到另一个包点'),
    ('封烟控图', '用烟雾技能争夺地图空间'),
    ('战术暂停', '队伍停下来重新沟通打法'),
    ('爆破模式', '进攻方下包、防守方拆包的核心玩法'),
    ('竞技模式', '带段位和竞技分变化的排位玩法'),
    ('普通模式', '没有排位压力的标准对局'),
    ('极速模式', '节奏更快、回合更少的短局玩法'),
    ('爆能快攻', '开局都有核心、节奏更快的娱乐模式'),
    ('乱斗模式', '不靠技能，主要练枪和找手感'),
    ('攻守交换', '半场结束后双方阵营互换'),
    ('回合胜利', '一小局完成目标后拿到分数'),
    ('下包', '进攻方把核心放到包点'),
    ('拆包', '防守方解除已经安装的核心'),
    ('保枪', '放弃当前回合，保住武器去下一局'),
    ('eco', '团队为了下一回合主动省经济'),
    ('强起', '经济不好但仍然强行购买装备'),
    ('半甲短枪', '预算有限时的折中购买方案'),
    ('全甲长枪', '经济充足时的完整购买配置'),
    ('技能灵球', '地图上可争夺的大招充能资源'),
    ('大招点数', '用于释放终极技能的资源'),
    ('假打', '制造进攻假象后换到另一边'),
    ('静步', '不发出脚步声慢慢靠近目标区'),
    ('rush', '靠速度和技能迅速打进包点'),
    ('交叉枪线', '两名队友从不同角度同时架住敌人'),
    ('非常规位', '敌人不容易预瞄到的站位'),
    ('单向烟雾', '自己能看见对手、对手难看见自己的烟'),
    ('点位', '固定投掷或释放技能的位置'),
    ('指挥', '负责做战术决策和临场调度的人'),
    ('报点', '把敌人位置和信息及时告诉队友'),
    ('一滴', '告诉队友敌人血量已经很低'),
    ('预瞄', '提前把准星放在敌人可能出现的位置'),
    ('peek', '短暂露身诱骗敌人开枪'),
    ('旋转跳', '跳出去看信息再撤回掩体'),
    ('补枪', '队友倒下后马上换掉对手'),
    ('拉枪定位', '快速把准星拉到敌人身上'),
    ('断后', '队伍推进时留人在后方抓时机'),
    ('二楼架点', '从高处或二层位置控制区域'),
    ('中路控制', '争夺地图中央带来的转点主动权'),
    ('包点回防', '防守方重新夺回已经失守的包点'),
    ('假拆骗枪', '点一下拆包来诱骗敌人露身'),
    ('真拆到底', '顶住压力持续拆包不松手'),
    ('队友发枪', '经济好的队友给别人购买武器'),
    ('赛点压力', '再输一局就结束比赛的紧张局面'),
    ('团队团灭', '全队合力消灭对方全部成员'),
    ('五杀高光', '单人击杀五名敌人的名场面'),
    ('莲华古城', '隐藏在密林深处的古城地图'),
    ('裂变峡谷', '地图结构被割裂成多片区域'),
    ('霓虹町', '充满都市霓虹感的地图名称'),
    ('日落之城', '夕阳氛围很强的城市地图'),
    ('森寒冬港', '寒冷港口风格的地图'),
    ('深海明珠', '带有水下城市想象的地图'),
    ('微风岛屿', '海岛和开阔长线较多的地图'),
    ('亚海悬城', '高低差和悬空结构明显的地图'),
    ('盐海矿镇', '矿镇主题的老牌地图'),
    ('隐世修所', '有三包点结构的经典地图'),
    ('幽邃地窟', '纵深感很强的地图名称'),
    ('源工重镇', '工业风和核心设施感很强的地图'),
    ('奥丁', '弹量充足、火力压制感很强的重武器'),
    ('标配', '每局基础配置里常见的手枪'),
    ('飞将', '适合远距离架点的狙击枪'),
    ('蜂刺', '近中距离压制节奏很快的冲锋枪'),
    ('鬼魅', '手枪局常见的稳定选择'),
    ('骇灵', '适合跑打和近距离交火的冲锋枪'),
    ('幻影', '稳定控枪和中距离交火常用步枪'),
    ('狂怒', '射速很快、近距离凶猛的手枪'),
    ('狂徒', '爆头收益很高的主战步枪'),
    ('獠犬', '近距离压迫感很强的霰弹枪'),
    ('莽侠', '火力持续输出的重型机枪'),
    ('冥驹', '一枪威慑力极强的重狙'),
    ('判官', '守近点时很容易打出惊喜的霰弹枪'),
    ('戍卫', '单点精准、适合稳健架枪的步枪'),
    ('雄鹿', '兼顾近战爆发和一定灵活性的霰弹枪'),
    ('战神', '压制力和弹量都很强的机枪'),
    ('正义', '伤害稳定、手枪局存在感高'),
    ('追猎', '适合点射和补枪的手枪'),
    ('近战', '跑图时常拿在手里的刀类武器'),
    ('捷风', '高速进场吸引火力的突破特工'),
    ('贤者', '能治疗和复活队友的辅助特工'),
    ('猎枭', '用侦查技能获取敌方信息的特工'),
    ('奇乐', '用设备守点和收集信息的特工'),
    ('幽影', '用烟雾遮挡视野帮助进攻或防守'),
    ('雷兹', '用爆炸物清点和压迫敌人的特工'),
    ('蝰蛇', '用毒幕分割战场视野的特工'),
    ('零', '用线和设备抓住敌人动向的哨位'),
    ('霓虹', '靠高速移动撕开防线的特工'),
    ('不死鸟', '用闪光和自保能力主动开打'),
    ('芮娜', '依靠击杀后续航继续打架'),
    ('尚勃勒', '用精准武器和陷阱控制长线'),
    ('斯凯', '用闪光鸟配合队友进攻'),
    ('铁臂', '用震荡和闪光帮助队友突破'),
    ('三角洲行动', '今晚开黑常被点名的搜打撤项目'),
    ('烽火地带', '进图先摸东西，活着出来才算赚'),
    ('全面战场', '一边抢点一边被载具教育的大场面'),
    ('黑鹰坠落', '合作战役里最有电影感的那条线'),
    ('卡战备', '差一点门槛时临时往身上塞装备'),
    ('零号大坝', '新手熟悉路线和撤离的常见地图'),
    ('长弓溪谷', '跑图很远但总觉得下一个点有货'),
    ('航天基地', '又肥又吵，大家都爱往里扎'),
    ('巴克什', '城区楼多门多，搜着搜着就迷路'),
    ('潮汐监狱', '看起来能发财，也可能把人关到急'),
    ('红狼', '最爱第一个冲出去的突击干员'),
    ('威龙', '进点前先把动静弄大的干员'),
    ('疾风', '跑起来队友都快追不上的干员'),
    ('蜂医', '残血队友最想喊他奶一口'),
    ('牧羊人', '控场和反制很烦人的工程干员'),
    ('乌鲁鲁', '喜欢用爆炸物把路打开的干员'),
    ('比特', '看到设备就想黑一下的干员'),
    ('深蓝', '单三最严厉的父亲'),
    ('露娜', '一眼扫出信息的侦察干员'),
    ('骇爪', '最会让对面电子设备难受的侦察'),
    ('蛊', '毒雾和化学味都很浓的角色'),
    ('无名', '不声不响摸过去的潜行干员'),
    ('银翼', '从高处把战场信息带回来的角色'),
    ('蝶', '救人可以腾出手架枪的角色'),
    ('小猪粮兑换', '把小猪粮转换成嗯呢币'),
    ('嗯呢币钱包', '店里的余额钱包'),
)

GAME_ALIASES = {
    'hangman': 'hangman',
    '猜词': 'hangman',
    '吊小人': 'hangman',
    'scramble': 'scramble',
    '乱序': 'scramble',
    '乱序词': 'scramble',
    'mastermind': 'mastermind',
    '密码': 'mastermind',
    '猜密码': 'mastermind',
    'blackjack': 'blackjack',
    '21点': 'blackjack',
    '二十一点': 'blackjack',
    'connect4': 'connect4',
    '四子棋': 'connect4',
    '连四': 'connect4',
    'bomb': 'bomb',
    '炸弹': 'bomb',
    '数字炸弹': 'bomb',
    'undercover': 'undercover',
    '卧底': 'undercover',
    '谁是卧底': 'undercover',
    'blackjack_pvp': 'blackjack_pvp',
    '21点对决': 'blackjack_pvp',
    '21点双人': 'blackjack_pvp',
    '21点pvp': 'blackjack_pvp',
    'pvp21': 'blackjack_pvp',
    '双人21点': 'blackjack_pvp',
}

COLOR_LABELS = {
    'red': '红',
    'blue': '蓝',
    'green': '绿',
    'yellow': '黄',
    'purple': '紫',
    'orange': '橙',
}

COLOR_ALIASES = {
    '红': 'red',
    '红色': 'red',
    'r': 'red',
    'red': 'red',
    '蓝': 'blue',
    '蓝色': 'blue',
    'b': 'blue',
    'blue': 'blue',
    '绿': 'green',
    '绿色': 'green',
    'g': 'green',
    'green': 'green',
    '黄': 'yellow',
    '黄色': 'yellow',
    'y': 'yellow',
    'yellow': 'yellow',
    '紫': 'purple',
    '紫色': 'purple',
    'p': 'purple',
    'purple': 'purple',
    '橙': 'orange',
    '橙色': 'orange',
    'o': 'orange',
    'orange': 'orange',
}

BLACKJACK_DEFAULT_RATING = 1000
BLACKJACK_DELTAS = {
    'natural_bj_win': 35,
    'dealer_bust': 25,
    'normal_win': 20,
    'draw': 5,
    'normal_loss': -15,
    'bust_loss': -20,
    'abandoned': -10,
}
BLACKJACK_WIN_KINDS = {'natural_bj_win', 'dealer_bust', 'normal_win'}
BLACKJACK_STREAK_BONUS = 5  # 连胜≥3 时,本局额外 +5
BLACKJACK_TIERS = (
    (1800, '王者'),
    (1600, '钻石'),
    (1400, '铂金'),
    (1200, '黄金'),
    (1000, '白银'),
    (0, '青铜'),
)
BLACKJACK_TIER_EMOJI = {
    '青铜': '🥉',
    '白银': '🥈',
    '黄金': '🥇',
    '铂金': '💠',
    '钻石': '💎',
    '王者': '👑',
}
BLACKJACK_OUTCOME_LABEL = {
    'natural_bj_win': '天选 21',
    'dealer_bust': '庄家爆牌',
    'normal_win': '点数压庄',
    'draw': '握手言和',
    'normal_loss': '点数告负',
    'bust_loss': '爆牌出局',
    'abandoned': '中途弃局',
}


CARD_SUITS = ('黑桃', '红心', '方块', '梅花')
CARD_RANKS = (
    ('A', 11),
    ('K', 10),
    ('Q', 10),
    ('J', 10),
    ('10', 10),
    ('9', 9),
    ('8', 8),
    ('7', 7),
    ('6', 6),
    ('5', 5),
    ('4', 4),
    ('3', 3),
    ('2', 2),
)


@dataclass
class MiniGameSession:
    game: str
    channel_id: str
    kook_id: str
    player_name: str = ''
    state: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self):
        self.updated_at = time.time()


_sessions = {}


def normalize_game_key(raw_value):
    text = str(raw_value or '').strip().lower()
    return GAME_ALIASES.get(text)


def menu_text():
    return (
        '**KOOK 游戏菜单**\n'
        '---\n'
        '`/游戏 猜词` - 猜中文词语\n'
        '`/游戏 乱序` - 根据打乱文字猜原词\n'
        '`/游戏 密码` - 颜色密码，例: `/游戏 猜 红 蓝 绿 黄`\n'
        '`/游戏 21点` - 和机器人庄家玩 21 点(带排位分,需绑账号)\n'
        '`/游戏 21点 @玩家` - 双人对决 21 点（独立 ELO 排位）\n'
        '`/游戏 四子棋` - 双人四子棋\n'
        '`/游戏 炸弹` - 数字炸弹 1-100（单人速通）\n'
        '`/游戏 炸弹 多人` - 多人接力炸弹（踩到的输）\n'
        '`/游戏 卧底` - 谁是卧底（4-8 人，AI 出题）\n'
        '`/游戏 排行 [游戏名]` - 查看排行榜,可填 四子棋/猜词/21点/21点对决/炸弹\n'
        '`/游戏 剧情` - 进入 AI 剧情互动游戏《灰区档案》\n'
        '---\n'
        '`/游戏 状态` 查看当前局，`/游戏 退出` 结束当前局。'
    )


def connect4_menu_text():
    return (
        '**四子棋**\n'
        '---\n'
        '`/游戏 四子棋 @玩家` - 开局\n'
        '`/游戏 落子 1-7` - 轮流下棋\n'
        '`/游戏 状态` - 查看棋盘\n'
        '`/游戏 退出` - 结束本频道对局\n'
        '`/游戏 排行 四子棋` - 查看四子棋排行榜'
    )


def start_game(channel_id, kook_id, player_name, game_key):
    _cleanup_expired_sessions()
    game = normalize_game_key(game_key) or game_key
    if game == 'connect4':
        return _result(connect4_menu_text(), ok=False)
    if game == 'undercover':
        return _result(undercover_menu_text(), ok=False)
    if game == 'blackjack_pvp':
        return _result(
            '21 点双人对决需要指定对手，例：`/游戏 21点 @对手`。\n'
            '不带 @ 则进入单人 vs 庄家模式。',
            ok=False,
        )
    if game not in {'hangman', 'scramble', 'mastermind', 'blackjack', 'bomb'}:
        return _result(menu_text(), ok=False)

    key = _session_key(channel_id, kook_id)
    existing = _sessions.get(key)
    if existing:
        return _result(
            f'你已经有一局 **{_game_label(existing.game)}** 正在进行。\n'
            '先发送 `/游戏 退出` 结束，或 `/游戏 状态` 查看当前局。',
            ok=False,
        )
    connect4_session = _find_connect4_session(channel_id, kook_id)
    if connect4_session:
        return _result(
            f'你已经在本频道的 **四子棋** 对局中。\n'
            f'轮到谁: {_connect4_current_player_text(connect4_session)}',
            ok=False,
        )
    bomb_multi = _sessions.get(_bomb_multi_key(channel_id))
    if bomb_multi and _bomb_multi_has_player(bomb_multi, kook_id):
        return _result(
            '你已经在本频道的多人数字炸弹局中。先 `/游戏 状态` 查看，或 `/游戏 退出` 结束。',
            ok=False,
        )
    undercover_session = _sessions.get(_undercover_key(channel_id))
    if undercover_session and _undercover_has_player(undercover_session, kook_id):
        return _result(
            '你已经在本频道的谁是卧底中。先 `/游戏 卧底 状态` 查看，或 `/游戏 卧底 退出`。',
            ok=False,
        )
    pvp_session = _find_blackjack_pvp_session(channel_id, kook_id)
    if pvp_session:
        return _result(
            '你已经在本频道的 21 点双人对决中。先 `/游戏 状态` 查看，或 `/游戏 退出` 结束。',
            ok=False,
        )

    session = MiniGameSession(
        game=game,
        channel_id=str(channel_id or 'unknown'),
        kook_id=str(kook_id or ''),
        player_name=str(player_name or ''),
    )
    if game == 'hangman':
        _start_hangman(session)
    elif game == 'scramble':
        _start_scramble(session)
    elif game == 'mastermind':
        _start_mastermind(session)
    elif game == 'blackjack':
        _start_blackjack(session)
    elif game == 'bomb':
        _start_bomb_solo(session)
    _sessions[key] = session
    return _result(f'已开启 **{_game_label(game)}**。\n\n{_render_session(session)}')


def get_status(channel_id, kook_id):
    _cleanup_expired_sessions()
    session = _sessions.get(_session_key(channel_id, kook_id))
    if not session:
        pvp_session = _find_blackjack_pvp_session(channel_id, kook_id) or _sessions.get(_blackjack_pvp_key(channel_id))
        if pvp_session:
            pvp_session.touch()
            return _result(_render_blackjack_pvp(pvp_session))
        connect4_session = _find_connect4_session(channel_id, kook_id) or _sessions.get(_connect4_key(channel_id))
        if connect4_session:
            connect4_session.touch()
            return _result(_render_connect4(connect4_session))
        bomb_multi = _sessions.get(_bomb_multi_key(channel_id))
        if bomb_multi:
            bomb_multi.touch()
            return _result(_render_bomb_multi(bomb_multi))
        undercover_session = _sessions.get(_undercover_key(channel_id))
        if undercover_session:
            undercover_session.touch()
            return _result(_render_undercover(undercover_session))
        return _result('你当前没有进行中的小游戏。\n\n' + menu_text(), ok=False)
    session.touch()
    return _result(_render_session(session))


def quit_game(channel_id, kook_id):
    session = _sessions.pop(_session_key(channel_id, kook_id), None)
    if not session:
        pvp_session = _find_blackjack_pvp_session(channel_id, kook_id)
        if pvp_session:
            return _blackjack_pvp_quit(pvp_session, kook_id)
        connect4_session = _find_connect4_session(channel_id, kook_id)
        if connect4_session:
            _sessions.pop(_connect4_key(channel_id), None)
            winner_id, winner_name = _connect4_forfeit_winner(connect4_session, kook_id)
            record = _build_record_payload(
                connect4_session,
                result='abandoned',
                winner_id=winner_id,
                winner_name=winner_name,
                end_reason='quit',
                abandoned_by=kook_id,
            )
            return _result(f'已结束 **四子棋**，由 {_player_text(kook_id)} 退出。', ended=True, record=record)
        bomb_multi = _sessions.get(_bomb_multi_key(channel_id))
        if bomb_multi and _bomb_multi_has_player(bomb_multi, kook_id):
            return _bomb_multi_quit(bomb_multi, kook_id)
        undercover_session = _sessions.get(_undercover_key(channel_id))
        if undercover_session and _undercover_has_player(undercover_session, kook_id):
            return _undercover_quit(undercover_session, kook_id)
        return _result('你当前没有进行中的小游戏。', ok=False)
    record = _build_record_payload(
        session,
        result='abandoned',
        end_reason='quit',
        abandoned_by=kook_id,
        outcome_kind='abandoned' if session.game == 'blackjack' else '',
    )
    return _result(f'已结束 **{_game_label(session.game)}**。', ended=True, record=record)


def start_connect4(channel_id, starter_id, starter_name, opponent_id, opponent_name=''):
    _cleanup_expired_sessions()
    channel_id = str(channel_id or 'unknown')
    starter_id = str(starter_id or '').strip()
    opponent_id = str(opponent_id or '').strip()
    if not starter_id:
        return _result('未获取到发起人的 KOOK 身份。', ok=False)
    if not opponent_id:
        return _result(connect4_menu_text(), ok=False)
    if starter_id == opponent_id:
        return _result('四子棋需要两位不同玩家。', ok=False)

    key = _connect4_key(channel_id)
    if _sessions.get(key):
        return _result('当前频道已经有一局四子棋正在进行，先 `/游戏 状态` 看看局面。', ok=False)
    for player_id in (starter_id, opponent_id):
        if _sessions.get(_session_key(channel_id, player_id)):
            return _result(f'{_player_text(player_id)} 当前有单人小游戏正在进行，请先 `/游戏 退出`。', ok=False)

    first_turn = random.randint(0, 1)
    session = MiniGameSession(
        game='connect4',
        channel_id=channel_id,
        kook_id=starter_id,
        player_name=str(starter_name or ''),
        state={
            'board': [[-1 for _ in range(7)] for _ in range(6)],
            'players': [
                {'id': starter_id, 'name': str(starter_name or '')},
                {'id': opponent_id, 'name': str(opponent_name or '')},
            ],
            'turn': first_turn,
            'winner': None,
            'draw': False,
            'moves': 0,
        },
    )
    _sessions[key] = session
    return _result('四子棋开局。\n\n' + _render_connect4(session))


def handle_connect4_move(channel_id, kook_id, column_text):
    _cleanup_expired_sessions()
    session = _find_connect4_session(channel_id, kook_id)
    if not session:
        return _result('你当前不在本频道的四子棋对局中。先 `/游戏 四子棋 @玩家` 开一局。', ok=False)

    session.touch()
    player_index = _connect4_player_index(session, kook_id)
    if player_index != int(session.state.get('turn', 0)):
        return _result(f'还没轮到你。当前回合: {_connect4_current_player_text(session)}', ok=False)

    try:
        column = int(str(column_text or '').strip()) - 1
    except Exception:
        return _result('请输入列号 1-7，例如 `/游戏 落子 4`。', ok=False)

    if column < 0 or column > 6:
        return _result('列号必须是 1-7。', ok=False)
    board = session.state['board']
    if board[0][column] != -1:
        return _result('这一列已经满了，换一列。', ok=False)

    row = None
    for candidate in range(5, -1, -1):
        if board[candidate][column] == -1:
            board[candidate][column] = player_index
            row = candidate
            break

    if row is None:
        return _result('这一列已经满了，换一列。', ok=False)

    session.state['moves'] = int(session.state.get('moves') or 0) + 1
    if _connect4_has_won(board, row, column, player_index):
        session.state['winner'] = player_index
        message = _render_connect4(session) + f'\n\n{_player_text(kook_id)} 连成四子，赢下本局。'
        _sessions.pop(_connect4_key(channel_id), None)
        record = _build_record_payload(
            session,
            result='win',
            winner_id=kook_id,
            winner_name=_connect4_player_name(session, kook_id),
            end_reason='connect4',
        )
        return _result(message, ended=True, record=record)

    if _connect4_board_full(board):
        session.state['draw'] = True
        message = _render_connect4(session) + '\n\n棋盘已满，本局平局。'
        _sessions.pop(_connect4_key(channel_id), None)
        record = _build_record_payload(session, result='draw', end_reason='board_full')
        return _result(message, ended=True, record=record)

    session.state['turn'] = 1 - player_index
    return _result(_render_connect4(session))


def handle_guess(channel_id, kook_id, guess_text):
    _cleanup_expired_sessions()
    key = _session_key(channel_id, kook_id)
    session = _sessions.get(key)
    if session:
        session.touch()
        if session.game == 'hangman':
            result = _guess_hangman(session, guess_text)
        elif session.game == 'scramble':
            result = _guess_scramble(session, guess_text)
        elif session.game == 'mastermind':
            result = _guess_mastermind(session, guess_text)
        elif session.game == 'bomb':
            result = _guess_bomb_solo(session, guess_text)
        else:
            return _result('21 点不用 `/游戏 猜`，请使用 `/游戏 要牌` 或 `/游戏 停牌`。', ok=False)
        if result.get('ended'):
            _sessions.pop(key, None)
        return result

    bomb_multi = _sessions.get(_bomb_multi_key(channel_id))
    if bomb_multi and _bomb_multi_has_player(bomb_multi, kook_id):
        return _guess_bomb_multi(bomb_multi, kook_id, guess_text)

    return _result('你当前没有进行中的猜谜类小游戏。先发送 `/游戏 猜词`、`/游戏 乱序`、`/游戏 密码` 或 `/游戏 炸弹`。', ok=False)


def handle_blackjack_action(channel_id, kook_id, action):
    _cleanup_expired_sessions()
    action_key = str(action or '').strip().lower()

    pvp_session = _find_blackjack_pvp_session(channel_id, kook_id)
    if pvp_session:
        pvp_session.touch()
        return _handle_blackjack_pvp_action(pvp_session, kook_id, action_key)

    key = _session_key(channel_id, kook_id)
    session = _sessions.get(key)
    if not session or session.game != 'blackjack':
        return _result('你当前没有进行中的 21 点。先发送 `/游戏 21点`。', ok=False)

    session.touch()
    if action_key in {'hit', 'h', '要牌', '拿牌'}:
        result = _blackjack_hit(session)
    elif action_key in {'stand', 's', '停牌', '不要', '开牌'}:
        result = _blackjack_stand(session)
    else:
        return _result('21 点操作只支持 `/游戏 要牌` 或 `/游戏 停牌`。', ok=False)

    if result.get('ended'):
        _sessions.pop(key, None)
    return result


def record_minigame_result(record_payload):
    """把一局小游戏结果写入数据库，调用方需要处在 Flask app context 中。"""
    payload = record_payload or {}
    game = normalize_game_key(payload.get('game')) or str(payload.get('game') or '').strip()
    if not game:
        return None

    from app.extensions import db
    from app.models.minigame import MiniGameRecord

    players = payload.get('players') or []
    player1 = _payload_player(players, 0)
    player2 = _payload_player(players, 1)
    player1_user = _resolve_user_by_kook_id(player1['id'])
    player2_user = _resolve_user_by_kook_id(player2['id'])
    winner_id = str(payload.get('winner_id') or '').strip()
    winner_user = _resolve_user_by_kook_id(winner_id)
    winner_name = str(payload.get('winner_name') or '').strip()
    if not winner_name and winner_id:
        winner_name = _payload_name_for(players, winner_id)

    started_at = _epoch_to_datetime(payload.get('started_at')) or datetime.utcnow()
    ended_at = _epoch_to_datetime(payload.get('ended_at')) or datetime.utcnow()
    duration_seconds = max(0, int((ended_at - started_at).total_seconds()))

    record = MiniGameRecord(
        game=game,
        game_label=_game_label(game),
        channel_id=str(payload.get('channel_id') or ''),
        player1_kook_id=player1['id'] or None,
        player1_user_id=player1_user.id if player1_user else None,
        player1_name=player1['name'] or _display_name_from_user(player1_user, '', player1['id']),
        player2_kook_id=player2['id'] or None,
        player2_user_id=player2_user.id if player2_user else None,
        player2_name=player2['name'] or _display_name_from_user(player2_user, '', player2['id']),
        winner_kook_id=winner_id or None,
        winner_user_id=winner_user.id if winner_user else None,
        winner_name=winner_name or _display_name_from_user(winner_user, '', winner_id),
        result=str(payload.get('result') or 'unknown')[:20],
        end_reason=str(payload.get('end_reason') or '')[:50] or None,
        abandoned_by_kook_id=str(payload.get('abandoned_by') or '').strip() or None,
        moves=int(payload.get('moves') or 0),
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
    )
    db.session.add(record)
    db.session.commit()
    return record


def blackjack_tier(rating):
    rating = int(rating or 0)
    for threshold, name in BLACKJACK_TIERS:
        if rating >= threshold:
            return name
    return '青铜'


def _blackjack_tier_progress(rating):
    """返回 (当前段位下界, 下一段位下界 or None, 下一段位名 or '')。"""
    sorted_tiers = sorted(BLACKJACK_TIERS, key=lambda item: item[0])
    cur_floor = sorted_tiers[0][0]
    next_floor = None
    next_name = ''
    for floor, name in sorted_tiers:
        if rating >= floor:
            cur_floor = floor
        else:
            next_floor = floor
            next_name = name
            break
    return cur_floor, next_floor, next_name


def _format_blackjack_rating_panel(before, after, base_delta, streak_bonus,
                                   prev_streak, new_streak, is_win, outcome):
    """构建 21 点排位结算 TUI 面板。"""
    delta = after - before
    tier = blackjack_tier(after)
    tier_emoji = BLACKJACK_TIER_EMOJI.get(tier, '🏅')
    cur_floor, next_floor, next_name = _blackjack_tier_progress(after)

    if next_floor is None:
        bar = '█' * 10
        progress_text = '巅峰段位 · 无人能及'
    else:
        span = max(1, next_floor - cur_floor)
        gained = max(0, after - cur_floor)
        ratio = min(1.0, gained / span)
        filled = int(round(ratio * 10))
        bar = '▰' * filled + '▱' * (10 - filled)
        next_emoji = BLACKJACK_TIER_EMOJI.get(next_name, '')
        progress_text = f'{int(ratio * 100)}% → {next_emoji} {next_name} · 还差 {next_floor - after}'

    if delta > 0:
        change_text = f'`+{delta} ▲`'
        score_emoji = '📈'
    elif delta < 0:
        change_text = f'`{delta} ▼`'
        score_emoji = '📉'
    else:
        change_text = '`±0 ─`'
        score_emoji = '📊'

    if is_win:
        if new_streak >= 5:
            streak_emoji = '🔥🔥'
        elif new_streak >= 3:
            streak_emoji = '🔥'
        else:
            streak_emoji = '✨'
        streak_text = f'×{new_streak}'
        if streak_bonus:
            streak_text += f'　`连胜+{streak_bonus}`'
    elif outcome == 'draw':
        streak_emoji = '🤝'
        streak_text = '×0'
    else:
        if prev_streak >= 3:
            streak_emoji = '💔'
            streak_text = f'×0　`{prev_streak} 连胜中断`'
        else:
            streak_emoji = '·'
            streak_text = '×0'

    outcome_label = BLACKJACK_OUTCOME_LABEL.get(outcome, '')
    sep = '━' * 30
    lines = [
        sep,
        f'🎰  **21 点 · 排位结算**　{("· " + outcome_label) if outcome_label else ""}',
        sep,
        f'🏅  段位　⤳　**{tier_emoji} {tier}**',
        f'{score_emoji}  分数　⤳　{before} ➜ **{after}**　{change_text}',
        f'{streak_emoji}  连胜　⤳　{streak_text}',
        f'📊  进度　⤳　`{bar}`　{progress_text}',
        sep,
    ]
    return '\n'.join(lines)


def apply_blackjack_rating(record_payload):
    """根据一局 21 点结果更新玩家排位分,返回展示文本。
    必须在 Flask app context 中调用;玩家未绑定账号则返回空。
    """
    payload = record_payload or {}
    if normalize_game_key(payload.get('game')) != 'blackjack':
        return ''
    outcome = str(payload.get('outcome_kind') or '').strip()
    if outcome not in BLACKJACK_DELTAS:
        return ''

    players = payload.get('players') or []
    kook_id = str((players[0] if players else {}).get('id') or '').strip()
    user = _resolve_user_by_kook_id(kook_id)
    if not user or not user.id:
        return ''

    from app.extensions import db
    from app.models.minigame import MiniGameRating

    rating_row = MiniGameRating.query.filter_by(user_id=user.id, game='blackjack').first()
    if not rating_row:
        rating_row = MiniGameRating(
            user_id=user.id,
            game='blackjack',
            rating=BLACKJACK_DEFAULT_RATING,
            peak_rating=BLACKJACK_DEFAULT_RATING,
            win_streak=0,
            games_played=0,
        )
        db.session.add(rating_row)

    before = int(rating_row.rating or BLACKJACK_DEFAULT_RATING)
    base_delta = int(BLACKJACK_DELTAS[outcome])
    is_win = outcome in BLACKJACK_WIN_KINDS
    prev_streak = int(rating_row.win_streak or 0)
    streak_bonus = BLACKJACK_STREAK_BONUS if (is_win and prev_streak >= 2) else 0
    delta = base_delta + streak_bonus

    after = max(0, before + delta)
    rating_row.rating = after
    rating_row.peak_rating = max(int(rating_row.peak_rating or 0), after)
    rating_row.games_played = int(rating_row.games_played or 0) + 1
    rating_row.win_streak = prev_streak + 1 if is_win else 0
    new_streak = int(rating_row.win_streak)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return ''

    return _format_blackjack_rating_panel(
        before=before,
        after=after,
        base_delta=base_delta,
        streak_bonus=streak_bonus,
        prev_streak=prev_streak,
        new_streak=new_streak,
        is_win=is_win,
        outcome=outcome,
    )


def _format_blackjack_rating_leaderboard(limit=10):
    from app.models.minigame import MiniGameRating
    from app.models.user import User

    limit = max(1, min(50, int(limit or 10)))
    rows = (
        MiniGameRating.query
        .filter_by(game='blackjack')
        .order_by(
            MiniGameRating.rating.desc(),
            MiniGameRating.peak_rating.desc(),
            MiniGameRating.games_played.asc(),
        )
        .limit(limit)
        .all()
    )

    sep = '━' * 32
    lines = [
        sep,
        '🎰  **21 点 · 排位榜 TOP {}**'.format(min(limit, len(rows) or limit)),
        sep,
    ]
    if not rows:
        lines.append('暂无排位记录,先来一局开荒吧。')
        lines.append(sep)
        return '\n'.join(lines)

    user_ids = [int(r.user_id) for r in rows]
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    rank_badges = {1: '🥇', 2: '🥈', 3: '🥉'}
    for idx, r in enumerate(rows, start=1):
        u = users.get(int(r.user_id))
        kook_id = getattr(u, 'kook_id', '') or ''
        mention = _player_text(kook_id) if kook_id else f"**{_display_name_from_user(u, '', kook_id)}**"
        tier = blackjack_tier(int(r.rating or 0))
        tier_emoji = BLACKJACK_TIER_EMOJI.get(tier, '🏅')
        badge = rank_badges.get(idx, f'`#{idx:>2}`')
        lines.append(
            f'{badge}  {mention}　{tier_emoji} **{tier}**　'
            f'`{int(r.rating)}`　巅峰 {int(r.peak_rating or 0)}　· {int(r.games_played or 0)} 局'
        )
    lines.append(sep)
    lines.append(
        '段位 ❯ 🥉 青铜 < 1000　🥈 白银 1000+　🥇 黄金 1200+　'
        '💠 铂金 1400+　💎 钻石 1600+　👑 王者 1800+'
    )
    lines.append(sep)
    return '\n'.join(lines)


def get_leaderboard(game_key=None, limit=10):
    """返回小游戏胜场排行榜。"""
    from app.models.minigame import MiniGameRecord
    from app.models.user import User

    game = normalize_game_key(game_key) if game_key else None
    raw_game = str(game_key or '').strip()
    if raw_game and raw_game not in {'全部', 'all'} and not game:
        return []

    query = MiniGameRecord.query
    if game:
        query = query.filter_by(game=game)
    records = query.order_by(MiniGameRecord.ended_at.asc(), MiniGameRecord.id.asc()).all()

    stats = {}
    for record in records:
        participants = [
            {
                'kook_id': record.player1_kook_id,
                'user_id': record.player1_user_id,
                'name': record.player1_name,
            },
            {
                'kook_id': record.player2_kook_id,
                'user_id': record.player2_user_id,
                'name': record.player2_name,
            },
        ]
        result = str(record.result or '')
        winner_id = str(record.winner_kook_id or '')
        abandoned_by = str(record.abandoned_by_kook_id or '')
        for participant in participants:
            kook_id = str(participant.get('kook_id') or '').strip()
            if not kook_id:
                continue
            item = stats.setdefault(kook_id, {
                'kook_id': kook_id,
                'user_id': participant.get('user_id'),
                'display_name': participant.get('name') or kook_id,
                'wins': 0,
                'losses': 0,
                'draws': 0,
                'abandons': 0,
                'total_games': 0,
            })
            if participant.get('user_id') and not item.get('user_id'):
                item['user_id'] = participant.get('user_id')
            if participant.get('name'):
                item['display_name'] = participant.get('name')

            item['total_games'] += 1
            if winner_id and winner_id == kook_id:
                item['wins'] += 1
            elif result == 'draw':
                item['draws'] += 1
            else:
                item['losses'] += 1
            if result == 'abandoned' and abandoned_by == kook_id:
                item['abandons'] += 1

    user_ids = [int(item['user_id']) for item in stats.values() if item.get('user_id')]
    users = {user.id: user for user in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    rows = []
    for item in stats.values():
        user = users.get(int(item['user_id'])) if item.get('user_id') else None
        item['display_name'] = _display_name_from_user(user, item.get('display_name'), item.get('kook_id'))
        completed = max(1, int(item['wins']) + int(item['losses']) + int(item['draws']))
        item['win_rate'] = round(int(item['wins']) * 100 / completed, 1)
        rows.append(item)

    rows.sort(key=lambda item: (
        -int(item['wins']),
        -float(item['win_rate']),
        -int(item['total_games']),
        str(item['kook_id']),
    ))
    limit = max(1, min(50, int(limit or 10)))
    for index, item in enumerate(rows[:limit], start=1):
        item['rank_no'] = index
    return rows[:limit]


def format_leaderboard(game_key=None, limit=10):
    game = normalize_game_key(game_key) if game_key else None
    raw_game = str(game_key or '').strip()
    if raw_game and raw_game not in {'全部', 'all'} and not game:
        available = '猜词、乱序词、密码色、21点、21点对决、四子棋、炸弹'
        return f'暂不支持 `{raw_game}` 的排行榜。可用游戏: {available}。'

    if game == 'blackjack':
        return _format_blackjack_rating_leaderboard(limit)
    if game == 'blackjack_pvp':
        return _format_blackjack_pvp_rating_leaderboard(limit)

    title = _game_label(game) if game else '全部小游戏'
    rows = get_leaderboard(game, limit=limit)
    lines = [f'**小游戏排行榜 · {title}**']
    if not rows:
        lines.append('暂无战绩，先来一局吧。')
        return '\n'.join(lines)

    for item in rows:
        mention = _player_text(item['kook_id'])
        extra = f'，弃权 {item["abandons"]}' if item.get('abandons') else ''
        lines.append(
            f'`#{item["rank_no"]}` {mention} '
            f'**{item["wins"]}胜** / {item["losses"]}负 / {item["draws"]}平{extra} '
            f'· 胜率 **{item["win_rate"]}%**'
        )
    return '\n'.join(lines)


def _result(message, ok=True, ended=False, record=None, side_effects=None, records=None):
    payload = {'ok': ok, 'message': message, 'ended': ended}
    if record:
        payload['record'] = record
    if records:
        payload['records'] = records
    if side_effects:
        payload['side_effects'] = side_effects
    return payload


def _session_key(channel_id, kook_id):
    return (str(channel_id or 'unknown'), str(kook_id or ''))


def _connect4_key(channel_id):
    return ('connect4', str(channel_id or 'unknown'))


def _find_connect4_session(channel_id, kook_id):
    session = _sessions.get(_connect4_key(channel_id))
    if not session or session.game != 'connect4':
        return None
    if not kook_id:
        return session
    return session if _connect4_player_index(session, kook_id) >= 0 else None


def _cleanup_expired_sessions():
    now = time.time()
    expired_keys = [
        key for key, session in _sessions.items()
        if now - float(session.updated_at or session.created_at or 0) > SESSION_TTL_SECONDS
    ]
    for key in expired_keys:
        _sessions.pop(key, None)


def _build_record_payload(session, result, winner_id='', winner_name='', end_reason='', abandoned_by='', outcome_kind=''):
    if session.game in ('connect4', 'blackjack_pvp'):
        players = session.state.get('players') or None
    else:
        players = None
    if not players:
        players = [{'id': session.kook_id, 'name': session.player_name}]
    cleaned_players = []
    for player in players[:2]:
        cleaned_players.append({
            'id': str(player.get('id') or '').strip(),
            'name': str(player.get('name') or '').strip(),
        })

    winner_id = str(winner_id or '').strip()
    winner_name = str(winner_name or '').strip() or _payload_name_for(cleaned_players, winner_id)
    return {
        'game': session.game,
        'channel_id': session.channel_id,
        'players': cleaned_players,
        'winner_id': winner_id,
        'winner_name': winner_name,
        'result': str(result or ''),
        'end_reason': str(end_reason or ''),
        'abandoned_by': str(abandoned_by or '').strip(),
        'outcome_kind': str(outcome_kind or ''),
        'moves': int(session.state.get('moves') or 0),
        'started_at': float(session.created_at or time.time()),
        'ended_at': time.time(),
    }


def _payload_player(players, index):
    try:
        player = (players or [])[index] or {}
    except (IndexError, TypeError):
        player = {}
    return {
        'id': str(player.get('id') or '').strip(),
        'name': str(player.get('name') or '').strip(),
    }


def _payload_name_for(players, kook_id):
    kook_id = str(kook_id or '').strip()
    if not kook_id:
        return ''
    for player in players or []:
        if str(player.get('id') or '').strip() == kook_id:
            return str(player.get('name') or '').strip()
    return ''


def _epoch_to_datetime(value):
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def _resolve_user_by_kook_id(kook_id):
    kook_id = str(kook_id or '').strip()
    if not kook_id:
        return None
    from app.models.user import User
    return (
        User.query
        .filter_by(kook_id=kook_id)
        .order_by(User.kook_bound.desc(), User.id.asc())
        .first()
    )


def _display_name_from_user(user=None, fallback_name='', kook_id=''):
    if user:
        for candidate in (user.player_nickname, user.kook_username, user.nickname, user.username):
            if candidate:
                return candidate
    return fallback_name or str(kook_id or '')


def game_label(game):
    return _game_label(game)


def _game_label(game):
    return {
        'hangman': '猜词',
        'scramble': '乱序词',
        'mastermind': '密码色',
        'blackjack': '21 点',
        'blackjack_pvp': '21 点 · 双人对决',
        'connect4': '四子棋',
        'bomb': '数字炸弹',
        'bomb_multi': '数字炸弹·多人',
        'undercover': '谁是卧底',
    }.get(game, game)


def _player_text(kook_id):
    return f'(met){kook_id}(met)' if kook_id else '玩家'


def _connect4_player_index(session, kook_id):
    kook_id = str(kook_id or '')
    players = session.state.get('players') or []
    for index, player in enumerate(players):
        if str(player.get('id') or '') == kook_id:
            return index
    return -1


def _connect4_current_player_text(session):
    players = session.state.get('players') or []
    turn = int(session.state.get('turn') or 0)
    if 0 <= turn < len(players):
        return _player_text(players[turn].get('id'))
    return '未知玩家'


def _connect4_player_name(session, kook_id):
    players = session.state.get('players') or []
    for player in players:
        if str(player.get('id') or '') == str(kook_id or ''):
            return str(player.get('name') or '')
    return ''


def _connect4_forfeit_winner(session, quitter_id):
    players = session.state.get('players') or []
    for player in players:
        if str(player.get('id') or '') != str(quitter_id or ''):
            return str(player.get('id') or ''), str(player.get('name') or '')
    return '', ''


def _connect4_board_full(board):
    return all(cell != -1 for cell in board[0])


def _connect4_has_won(board, row, column, player_index):
    directions = ((1, 0), (0, 1), (1, 1), (1, -1))
    for dr, dc in directions:
        count = 1
        count += _connect4_count_direction(board, row, column, player_index, dr, dc)
        count += _connect4_count_direction(board, row, column, player_index, -dr, -dc)
        if count >= 4:
            return True
    return False


def _connect4_count_direction(board, row, column, player_index, dr, dc):
    count = 0
    r = row + dr
    c = column + dc
    while 0 <= r < 6 and 0 <= c < 7 and board[r][c] == player_index:
        count += 1
        r += dr
        c += dc
    return count


def _render_connect4(session):
    state = session.state
    board = state.get('board') or []
    players = state.get('players') or []
    piece_map = {-1: '⚫', 0: '🔴', 1: '🟡'}
    lines = [
        '**四子棋**',
        f'🔴 {_player_text(players[0]["id"]) if len(players) > 0 else "玩家1"}',
        f'🟡 {_player_text(players[1]["id"]) if len(players) > 1 else "玩家2"}',
        '',
        '`1 2 3 4 5 6 7`',
    ]
    for row in board:
        lines.append(''.join(piece_map.get(cell, '⚫') for cell in row))
    if state.get('winner') is not None:
        winner = players[int(state['winner'])]['id']
        lines.append(f'获胜: {_player_text(winner)}')
    elif state.get('draw'):
        lines.append('结果: 平局')
    else:
        lines.append(f'当前回合: {_connect4_current_player_text(session)}')
        lines.append('操作: `/游戏 落子 1-7`，退出: `/游戏 退出`')
    return '\n'.join(lines)


def _choose_word(min_length=1):
    entries = [_word_entry(item) for item in WORDS]
    entries = [entry for entry in entries if entry[0]]
    candidates = [entry for entry in entries if len(entry[0]) >= int(min_length or 1)]
    if not candidates:
        candidates = entries
    if not candidates:
        return '无畏契约', '默认题库'
    return random.choice(candidates)


def _word_entry(item):
    if isinstance(item, dict):
        word = item.get('word') or item.get('text') or ''
        hint = item.get('hint') or item.get('tip') or ''
    elif isinstance(item, (list, tuple)):
        word = item[0] if len(item) >= 1 else ''
        hint = item[1] if len(item) >= 2 else ''
    else:
        word = item
        hint = ''
    return _normalize_word(word), str(hint or '').strip()


def _normalize_word(text):
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]', '', str(text or '').lower())


def _start_hangman(session):
    word, hint = _choose_word(min_length=1)
    session.state = {
        'word': word,
        'hint': hint,
        'revealed': ['_' for _ in word],
        'lives': 8,
        'guessed': [],
        'missed_words': [],
        'moves': 0,
    }


def _guess_hangman(session, guess_text):
    guess = _normalize_word(guess_text)
    state = session.state
    word = state['word']
    if not guess:
        return _result('请输入要猜的字或完整词语，例如 `/游戏 猜 契`。', ok=False)
    if len(guess) > 1 and len(guess) != len(word):
        return _result('猜完整词语时长度要和答案一致；否则请只猜一个字。', ok=False)

    state['moves'] = int(state.get('moves') or 0) + 1
    if len(guess) == len(word):
        if guess == word:
            state['revealed'] = list(word)
            record = _build_record_payload(session, result='win', winner_id=session.kook_id, winner_name=session.player_name, end_reason='solved')
            return _result(_render_hangman(session) + '\n\n猜对了，漂亮收工。', ended=True, record=record)
        state['lives'] -= 1
        state['missed_words'].append(guess)
    else:
        char = guess
        if char in state['guessed']:
            state['moves'] = max(0, int(state.get('moves') or 0) - 1)
            return _result(_render_hangman(session) + f'\n\n`{char}` 已经猜过了，不扣次数。')
        state['guessed'].append(char)
        if char in word:
            for index, item in enumerate(word):
                if item == char:
                    state['revealed'][index] = char
        else:
            state['lives'] -= 1

    if '_' not in state['revealed']:
        record = _build_record_payload(session, result='win', winner_id=session.kook_id, winner_name=session.player_name, end_reason='solved')
        return _result(_render_hangman(session) + '\n\n猜对了，漂亮收工。', ended=True, record=record)
    if state['lives'] <= 0:
        record = _build_record_payload(session, result='loss', end_reason='out_of_lives')
        return _result(_render_hangman(session, reveal=True) + '\n\n次数用完，本局结束。', ended=True, record=record)
    return _result(_render_hangman(session))


def _render_hangman(session, reveal=False):
    state = session.state
    word = state['word']
    visible = ' '.join(list(word) if reveal else state['revealed'])
    guessed = ', '.join(state['guessed']) if state['guessed'] else '-'
    missed_words = ', '.join(state['missed_words']) if state['missed_words'] else '-'
    hint = state.get('hint') or '暂无'
    answer = f'\n答案: `{word}`' if reveal else ''
    return (
        '**猜词**\n'
        f'提示: `{hint}`\n'
        f'字数: **{len(word)}**\n'
        f'剩余机会: **{state["lives"]}**\n'
        f'词语: `{visible}`\n'
        f'已猜字符: `{guessed}`\n'
        f'猜错词语: `{missed_words}`\n'
        f'{answer}\n'
        '操作: `/游戏 猜 内容`（可填 1 个字或完整词）'
    )


def _start_scramble(session):
    word, hint = _choose_word(min_length=2)
    session.state = {
        'word': word,
        'hint': hint,
        'scrambled': _scramble_word(word),
        'attempts': 6,
        'history': [],
        'moves': 0,
    }


def _guess_scramble(session, guess_text):
    guess = _normalize_word(guess_text)
    state = session.state
    if not guess:
        return _result('请输入你还原出的词语，例如 `/游戏 猜 无畏契约`。', ok=False)

    state['history'].append(guess)
    state['moves'] = int(state.get('moves') or 0) + 1
    if guess == state['word']:
        record = _build_record_payload(session, result='win', winner_id=session.kook_id, winner_name=session.player_name, end_reason='solved')
        return _result(_render_scramble(session, reveal=True) + '\n\n还原成功。', ended=True, record=record)

    state['attempts'] -= 1
    if state['attempts'] <= 0:
        record = _build_record_payload(session, result='loss', end_reason='out_of_attempts')
        return _result(_render_scramble(session, reveal=True) + '\n\n次数用完，本局结束。', ended=True, record=record)
    return _result(_render_scramble(session) + '\n\n没对，再试一手。')


def _render_scramble(session, reveal=False):
    state = session.state
    history = ', '.join(state['history'][-5:]) if state['history'] else '-'
    answer = f'\n答案: `{state["word"]}`' if reveal else ''
    hint = state.get('hint') or '暂无'
    return (
        '**乱序词**\n'
        f'提示: `{hint}`\n'
        f'字数: **{len(state["word"])}**\n'
        f'打乱文字: `{state["scrambled"]}`\n'
        f'剩余次数: **{state["attempts"]}**\n'
        f'最近猜测: `{history}`\n'
        '操作: `/游戏 猜 内容`（填写完整词）'
        f'{answer}'
    )


def _scramble_word(word):
    chars = list(str(word or ''))
    if len(chars) <= 1:
        return ''.join(chars)
    best = ''.join(reversed(chars))
    for _ in range(30):
        candidate_chars = chars[:]
        random.shuffle(candidate_chars)
        candidate = ''.join(candidate_chars)
        if candidate != word:
            return candidate
    return best if best != word else ''.join(chars)


def _start_mastermind(session):
    code = random.sample(list(COLOR_LABELS.keys()), 4)
    session.state = {
        'code': code,
        'attempts': 10,
        'history': [],
        'moves': 0,
    }


def _guess_mastermind(session, guess_text):
    parsed, error = _parse_color_guess(guess_text)
    if error:
        return _result(error, ok=False)

    state = session.state
    code = state['code']
    exact = sum(1 for index, color in enumerate(parsed) if code[index] == color)
    misplaced = sum(1 for color in parsed if color in code) - exact
    state['history'].append({'guess': parsed, 'exact': exact, 'misplaced': misplaced})
    state['moves'] = int(state.get('moves') or 0) + 1

    if exact == 4:
        record = _build_record_payload(session, result='win', winner_id=session.kook_id, winner_name=session.player_name, end_reason='solved')
        return _result(_render_mastermind(session, reveal=True) + '\n\n密码破译成功。', ended=True, record=record)

    state['attempts'] -= 1
    if state['attempts'] <= 0:
        record = _build_record_payload(session, result='loss', end_reason='out_of_attempts')
        return _result(_render_mastermind(session, reveal=True) + '\n\n次数用完，本局结束。', ended=True, record=record)
    return _result(_render_mastermind(session))


def _parse_color_guess(raw_text):
    text = str(raw_text or '').strip().lower()
    if not text:
        return None, '请输入 4 个颜色，例如 `/游戏 猜 红 蓝 绿 黄`。'

    tokens = [item for item in re.split(r'[\s,，/、;；]+', text) if item]
    if len(tokens) == 1 and len(tokens[0]) == 4 and all(ch in COLOR_ALIASES for ch in tokens[0]):
        tokens = list(tokens[0])

    colors = []
    for token in tokens:
        color = COLOR_ALIASES.get(token)
        if not color:
            available = '、'.join(COLOR_LABELS.values())
            return None, f'颜色 `{token}` 不认识。可用颜色: {available}。'
        colors.append(color)

    if len(colors) != 4:
        return None, '需要正好 4 个颜色，例如 `/游戏 猜 红 蓝 绿 黄`。'
    if len(set(colors)) != 4:
        return None, '同一局里每次猜测不能重复颜色。'
    return colors, None


def _render_mastermind(session, reveal=False):
    state = session.state
    lines = ['**密码色**', f'剩余次数: **{state["attempts"]}**']
    lines.append('可用颜色: `红 蓝 绿 黄 紫 橙`')
    lines.append('操作: `/游戏 猜 内容`（例如 `/游戏 猜 红 蓝 绿 黄`）')
    if state['history']:
        lines.append('最近猜测:')
        for index, item in enumerate(state['history'][-6:], start=max(1, len(state['history']) - 5)):
            guess = ' '.join(COLOR_LABELS[color] for color in item['guess'])
            lines.append(f'`{index}.` {guess} -> 位置对 **{item["exact"]}**，颜色对位置错 **{item["misplaced"]}**')
    if reveal:
        answer = ' '.join(COLOR_LABELS[color] for color in state['code'])
        lines.append(f'答案: `{answer}`')
    return '\n'.join(lines)


def _start_blackjack(session):
    deck = [(rank, value, suit) for suit in CARD_SUITS for rank, value in CARD_RANKS]
    random.shuffle(deck)
    session.state = {
        'deck': deck,
        'player': [_deal(deck), _deal(deck)],
        'dealer': [_deal(deck), _deal(deck)],
        'finished': False,
        'result': '',
        'moves': 0,
    }


def _deal(deck):
    return deck.pop()


def _hand_value(cards):
    total = 0
    aces = 0
    for rank, value, _suit in cards:
        total += value
        if rank == 'A':
            aces += 1
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def _hand_display(cards):
    """带 A 的软牌显示成 `硬/软`,例如 5+A 显示 6/16;无活 A 或软=硬时只显示一个数。"""
    has_ace = any(rank == 'A' for rank, _v, _s in cards)
    if not has_ace:
        return str(_hand_value(cards))
    hard = sum((1 if rank == 'A' else value) for rank, value, _s in cards)
    soft = hard + 10
    if soft <= 21 and soft != hard:
        return f'{hard}/{soft}'
    return str(_hand_value(cards))


def _card_text(card):
    rank, _value, suit = card
    return f'{suit}{rank}'


def _blackjack_hit(session):
    state = session.state
    state['moves'] = int(state.get('moves') or 0) + 1
    state['player'].append(_deal(state['deck']))
    if _hand_value(state['player']) > 21:
        state['finished'] = True
        state['result'] = '你爆牌了，庄家胜。'
        record = _build_record_payload(session, result='loss', end_reason='bust', outcome_kind='bust_loss')
        return _result(_render_blackjack(session) + '\n\n' + state['result'], ended=True, record=record)
    return _result(_render_blackjack(session))


def _blackjack_stand(session):
    state = session.state
    state['moves'] = int(state.get('moves') or 0) + 1
    while _hand_value(state['dealer']) < 17:
        state['dealer'].append(_deal(state['deck']))

    player_value = _hand_value(state['player'])
    dealer_value = _hand_value(state['dealer'])
    player_natural = len(state['player']) == 2 and player_value == 21
    if dealer_value > 21:
        result = '庄家爆牌，你赢了。'
        record_result = 'win'
        winner_id = session.kook_id
        outcome_kind = 'dealer_bust'
    elif player_value > dealer_value:
        result = '你赢了。'
        record_result = 'win'
        winner_id = session.kook_id
        outcome_kind = 'natural_bj_win' if player_natural else 'normal_win'
    elif player_value == dealer_value:
        result = '平局。'
        record_result = 'draw'
        winner_id = ''
        outcome_kind = 'draw'
    else:
        result = '庄家胜。'
        record_result = 'loss'
        winner_id = ''
        outcome_kind = 'normal_loss'

    state['finished'] = True
    state['result'] = result
    record = _build_record_payload(
        session,
        result=record_result,
        winner_id=winner_id,
        winner_name=session.player_name if winner_id else '',
        end_reason='stand',
        outcome_kind=outcome_kind,
    )
    return _result(_render_blackjack(session) + '\n\n' + result, ended=True, record=record)


def _render_blackjack(session):
    state = session.state
    finished = bool(state.get('finished'))
    player_cards = ' '.join(_card_text(card) for card in state['player'])
    dealer_cards = ' '.join(_card_text(card) for card in state['dealer']) if finished else f'{_card_text(state["dealer"][0])} [暗牌]'
    dealer_value = _hand_display(state['dealer']) if finished else _hand_display([state['dealer'][0]])
    player_display = _hand_display(state['player'])
    lines = [
        '**21 点**',
        f'庄家: `{dealer_cards}` = **{dealer_value}**' + ('' if finished else ' + 暗牌'),
        f'你: `{player_cards}` = **{player_display}**',
    ]
    if not finished:
        if '/' in player_display:
            lines.append('💡 含 A 时显示 `硬/软` 两种点数,A 在不爆牌时按 11 计,会爆时自动按 1。')
        lines.append('操作: 点击下方按钮，或发送 `/游戏 要牌` / `/游戏 停牌`')
    return '\n'.join(lines)


def _render_session(session):
    if session.game == 'hangman':
        return _render_hangman(session)
    if session.game == 'scramble':
        return _render_scramble(session)
    if session.game == 'mastermind':
        return _render_mastermind(session)
    if session.game == 'blackjack':
        return _render_blackjack(session)
    if session.game == 'blackjack_pvp':
        return _render_blackjack_pvp(session)
    if session.game == 'bomb':
        return _render_bomb_solo(session)
    if session.game == 'bomb_multi':
        return _render_bomb_multi(session)
    if session.game == 'undercover':
        return _render_undercover(session)
    return menu_text()


# ============================================================
# 21 点 · 双人 PvP（频道级，独立 ELO 排位分）
# ============================================================

BLACKJACK_PVP_DEFAULT_RATING = 1000
BLACKJACK_PVP_K_FACTOR = 24
BLACKJACK_PVP_STREAK_BONUS = 5


def _blackjack_pvp_key(channel_id):
    return ('blackjack_pvp', str(channel_id or 'unknown'))


def _find_blackjack_pvp_session(channel_id, kook_id=None):
    session = _sessions.get(_blackjack_pvp_key(channel_id))
    if not session or session.game != 'blackjack_pvp':
        return None
    if not kook_id:
        return session
    return session if _blackjack_pvp_player_index(session, kook_id) >= 0 else None


def _blackjack_pvp_player_index(session, kook_id):
    kook_id = str(kook_id or '')
    if not kook_id:
        return -1
    for index, player in enumerate(session.state.get('players') or []):
        if str(player.get('id') or '') == kook_id:
            return index
    return -1


def start_blackjack_pvp(channel_id, starter_id, starter_name, opponent_id, opponent_name=''):
    """发起一局 21 点 PvP（招募阶段，等对手接受）。"""
    _cleanup_expired_sessions()
    channel_id = str(channel_id or 'unknown')
    starter_id = str(starter_id or '').strip()
    opponent_id = str(opponent_id or '').strip()
    if not starter_id:
        return _result('未获取到发起人的 KOOK 身份。', ok=False)
    if not opponent_id:
        return _result(
            '请 @ 一名对手发起 PvP，例：`/游戏 21点 @对手`。\n'
            '不带 @ 则进入单人 vs 庄家模式。',
            ok=False,
        )
    if starter_id == opponent_id:
        return _result('21 点对决需要两位不同玩家。', ok=False)

    key = _blackjack_pvp_key(channel_id)
    if _sessions.get(key):
        return _result('当前频道已经有一局 21 点对决，先 `/游戏 状态` 看看。', ok=False)
    for player_id in (starter_id, opponent_id):
        if _sessions.get(_session_key(channel_id, player_id)):
            return _result(
                f'{_player_text(player_id)} 当前有别的小游戏在进行，请先 `/游戏 退出`。',
                ok=False,
            )
    if _sessions.get(_connect4_key(channel_id)):
        return _result('当前频道有四子棋进行中。', ok=False)
    if _sessions.get(_bomb_multi_key(channel_id)):
        return _result('当前频道有多人炸弹进行中。', ok=False)
    if _sessions.get(_undercover_key(channel_id)):
        return _result('当前频道有谁是卧底进行中。', ok=False)

    session = MiniGameSession(
        game='blackjack_pvp',
        channel_id=channel_id,
        kook_id=starter_id,
        player_name=str(starter_name or ''),
        state={
            'phase': 'invited',
            'host_id': starter_id,
            'opponent_id': opponent_id,
            'players': [
                {'id': starter_id, 'name': str(starter_name or ''), 'hand': [], 'status': 'waiting'},
                {'id': opponent_id, 'name': str(opponent_name or ''), 'hand': [], 'status': 'waiting'},
            ],
            'deck': [],
            'turn': 0,
            'moves': 0,
        },
    )
    _sessions[key] = session
    return _result(
        '**21 点 · 双人对决** 邀请发出。\n'
        f'{_player_text(starter_id)} ⚔️ {_player_text(opponent_id)}\n'
        '对手发送 `/游戏 21点 接受` 接战，或 `/游戏 21点 拒绝` 谢绝；'
        '`/游戏 退出` 撤回邀请。\n'
        '邀请 30 分钟内有效。'
    )


def accept_blackjack_pvp(channel_id, kook_id, kook_name=''):
    """对手接受邀请，发牌进入对局。"""
    session = _sessions.get(_blackjack_pvp_key(channel_id))
    if not session:
        return _result('当前频道没有 21 点对决邀请。', ok=False)
    if session.state.get('phase') != 'invited':
        return _result('对局已开始。`/游戏 状态` 查看。', ok=False)
    if str(session.state.get('opponent_id') or '') != str(kook_id or ''):
        return _result('这局邀请不是给你的。', ok=False)
    if _sessions.get(_session_key(session.channel_id, kook_id)):
        return _result('你当前有别的小游戏在进行，请先 `/游戏 退出`。', ok=False)

    if kook_name:
        for player in session.state.get('players') or []:
            if str(player.get('id') or '') == str(kook_id):
                player['name'] = str(kook_name)
                break

    deck = [(rank, value, suit) for suit in CARD_SUITS for rank, value in CARD_RANKS]
    random.shuffle(deck)
    session.state['deck'] = deck
    for player in session.state.get('players') or []:
        player['hand'] = [_deal(deck), _deal(deck)]
        player['status'] = 'playing'
    session.state['phase'] = 'playing'
    session.state['turn'] = 0
    session.touch()

    host_id = session.state.get('host_id') or ''
    return _result(
        f'{_player_text(kook_id)} 接战！发牌完毕，{_player_text(host_id)} 先手。\n\n'
        + _render_blackjack_pvp(session)
    )


def decline_blackjack_pvp(channel_id, kook_id):
    session = _sessions.get(_blackjack_pvp_key(channel_id))
    if not session:
        return _result('当前频道没有 21 点对决邀请。', ok=False)
    if session.state.get('phase') != 'invited':
        return _result('对局已经开始，无法拒绝。', ok=False)
    if str(session.state.get('opponent_id') or '') != str(kook_id or ''):
        return _result('这局邀请不是给你的。', ok=False)
    _sessions.pop(_blackjack_pvp_key(channel_id), None)
    return _result(f'{_player_text(kook_id)} 谢绝了对决，邀请已撤销。', ended=True)


def _handle_blackjack_pvp_action(session, kook_id, action_key):
    state = session.state
    phase = state.get('phase', 'invited')
    if phase == 'invited':
        return _result('对局还没开始，等待对手 `/游戏 21点 接受`。', ok=False)
    if phase == 'finished':
        return _result('对局已结束。', ok=False)

    players = state.get('players') or []
    if not players:
        return _result('对局玩家信息异常。', ok=False)
    turn = int(state.get('turn') or 0)
    current = players[turn % len(players)]
    if str(current.get('id') or '') != str(kook_id or ''):
        return _result(
            f'还没轮到你。当前: {_player_text(current.get("id"))}',
            ok=False,
        )

    if action_key in {'hit', 'h', '要牌', '拿牌'}:
        return _blackjack_pvp_hit(session, current)
    if action_key in {'stand', 's', '停牌', '不要', '开牌'}:
        return _blackjack_pvp_stand(session, current)
    return _result('21 点操作只支持 `/游戏 要牌` 或 `/游戏 停牌`。', ok=False)


def _blackjack_pvp_hit(session, player):
    state = session.state
    state['moves'] = int(state.get('moves') or 0) + 1
    deck = state.get('deck') or []
    if not deck:
        return _blackjack_pvp_resolve(session, end_reason='deck_empty')
    player['hand'].append(_deal(deck))
    if _hand_value(player['hand']) > 21:
        player['status'] = 'bust'
        return _blackjack_pvp_advance_turn(
            session,
            prefix=f'{_player_text(player["id"])} 抽到 `{_card_text(player["hand"][-1])}` → 💥 爆牌\n\n',
        )
    return _result(_render_blackjack_pvp(session))


def _blackjack_pvp_stand(session, player):
    player['status'] = 'stand'
    return _blackjack_pvp_advance_turn(
        session,
        prefix=f'{_player_text(player["id"])} 停牌（{_hand_display(player["hand"])}）。\n\n',
    )


def _blackjack_pvp_advance_turn(session, prefix=''):
    """切到下一个仍在 'playing' 的玩家；都结束就结算。"""
    state = session.state
    players = state.get('players') or []
    n = len(players)
    if n == 0:
        return _result('对局玩家信息异常。', ok=False)
    cur = int(state.get('turn') or 0)
    for step in range(1, n + 1):
        idx = (cur + step) % n
        if (players[idx].get('status') or '') == 'playing':
            state['turn'] = idx
            session.touch()
            return _result(prefix + _render_blackjack_pvp(session))
    return _blackjack_pvp_resolve(session, prefix=prefix)


def _blackjack_pvp_resolve(session, prefix='', end_reason='resolve'):
    state = session.state
    state['phase'] = 'finished'
    players = state.get('players') or []
    if len(players) < 2:
        _sessions.pop(_blackjack_pvp_key(session.channel_id), None)
        return _result('对局玩家信息异常，已结束。', ok=False, ended=True)

    p1, p2 = players[0], players[1]
    v1, v2 = _hand_value(p1.get('hand') or []), _hand_value(p2.get('hand') or [])
    bust1, bust2 = v1 > 21, v2 > 21

    if bust1 and bust2:
        winner_idx = -1
        result_text = '双方爆牌 💥💥 平局 🤝'
    elif bust1:
        winner_idx = 1
        result_text = f'{_player_text(p1["id"])} 爆牌 💥，{_player_text(p2["id"])} 不战而胜 🏆'
    elif bust2:
        winner_idx = 0
        result_text = f'{_player_text(p2["id"])} 爆牌 💥，{_player_text(p1["id"])} 不战而胜 🏆'
    elif v1 > v2:
        winner_idx = 0
        result_text = f'{_player_text(p1["id"])} 点数压制（**{v1}** vs {v2}），胜 🏆'
    elif v2 > v1:
        winner_idx = 1
        result_text = f'{_player_text(p2["id"])} 点数压制（**{v2}** vs {v1}），胜 🏆'
    else:
        winner_idx = -1
        result_text = f'点数相同（**{v1}** vs **{v2}**），平局 🤝'

    if winner_idx >= 0:
        winner = players[winner_idx]
        record_result = 'win'
        winner_id = str(winner.get('id') or '')
        winner_name = str(winner.get('name') or '')
        outcome_kind = 'pvp_win'
    else:
        winner_id = ''
        winner_name = ''
        record_result = 'draw'
        outcome_kind = 'pvp_draw'

    record = _build_record_payload(
        session,
        result=record_result,
        winner_id=winner_id,
        winner_name=winner_name,
        end_reason=end_reason,
        outcome_kind=outcome_kind,
    )
    _sessions.pop(_blackjack_pvp_key(session.channel_id), None)
    message = prefix + _render_blackjack_pvp(session, finished=True) + '\n\n' + result_text
    return _result(message, ended=True, record=record)


def _blackjack_pvp_quit(session, kook_id):
    state = session.state
    phase = state.get('phase', 'invited')
    host_id = str(state.get('host_id') or '')
    opponent_id = str(state.get('opponent_id') or '')
    quitter = str(kook_id or '')

    if phase == 'invited':
        if quitter not in (host_id, opponent_id):
            return _result('你不在这局对决中。', ok=False)
        _sessions.pop(_blackjack_pvp_key(session.channel_id), None)
        return _result(f'已撤销 21 点对决邀请（由 {_player_text(quitter)} 取消）。', ended=True)

    quitter_idx = _blackjack_pvp_player_index(session, quitter)
    if quitter_idx < 0:
        return _result('你不在这局对决中。', ok=False)
    players = state.get('players') or []
    winner = players[1 - quitter_idx] if len(players) >= 2 else {}
    state['phase'] = 'finished'
    record = _build_record_payload(
        session,
        result='abandoned',
        winner_id=str(winner.get('id') or ''),
        winner_name=str(winner.get('name') or ''),
        end_reason='quit',
        abandoned_by=quitter,
        outcome_kind='pvp_abandon',
    )
    _sessions.pop(_blackjack_pvp_key(session.channel_id), None)
    return _result(
        f'{_player_text(quitter)} 弃局，{_player_text(winner.get("id"))} 不战而胜。',
        ended=True,
        record=record,
    )


def _render_blackjack_pvp(session, finished=False):
    state = session.state
    players = state.get('players') or []
    phase = state.get('phase', 'invited')
    finished = finished or phase == 'finished'
    lines = ['**21 点 · 双人对决**']

    if phase == 'invited':
        host_id = state.get('host_id') or ''
        opp_id = state.get('opponent_id') or ''
        lines.append(f'{_player_text(host_id)} 发出邀请，等待 {_player_text(opp_id)} 接战。')
        lines.append('对手 `/游戏 21点 接受` 进入对局，`/游戏 21点 拒绝` 谢绝。')
        return '\n'.join(lines)

    turn = int(state.get('turn') or 0)
    current_id = ''
    if not finished and players:
        current_id = str(players[turn % len(players)].get('id') or '')
    for player in players:
        hand = player.get('hand') or []
        cards = ' '.join(_card_text(card) for card in hand) or '-'
        value_text = _hand_display(hand) if hand else '0'
        status = player.get('status') or 'playing'
        if finished:
            tag_map = {
                'playing': '',
                'stand': ' · 停牌',
                'bust': ' · 💥 爆牌',
                'waiting': ' · 等待中',
            }
            tag = tag_map.get(status, '')
        else:
            if status == 'bust':
                tag = ' · 💥 爆牌'
            elif status == 'stand':
                tag = ' · 停牌'
            else:
                tag = ''
        marker = ''
        if not finished and str(player.get('id') or '') == current_id:
            marker = ' ◀ 当前回合'
        lines.append(
            f'{_player_text(player["id"])}: `{cards}` = **{value_text}**{tag}{marker}'
        )

    if not finished and current_id:
        lines.append('')
        lines.append(
            f'轮到 {_player_text(current_id)} 决策：`/游戏 要牌` 或 `/游戏 停牌`。'
        )
    return '\n'.join(lines)


# ----- ELO 排位分（双人 PvP，需双方都绑账号才更新） -----

def apply_blackjack_pvp_rating(record_payload):
    """根据一局 PvP 21 点结果更新两位玩家的 ELO 排位分,返回展示文本。
    必须在 Flask app context 中调用;任一玩家未绑账号则返回空。
    """
    payload = record_payload or {}
    if str(payload.get('game') or '') != 'blackjack_pvp':
        return ''
    outcome = str(payload.get('outcome_kind') or '').strip()
    if outcome not in {'pvp_win', 'pvp_draw', 'pvp_abandon'}:
        return ''
    players = payload.get('players') or []
    if len(players) < 2:
        return ''

    p1_id = str(players[0].get('id') or '').strip()
    p2_id = str(players[1].get('id') or '').strip()
    p1_user = _resolve_user_by_kook_id(p1_id)
    p2_user = _resolve_user_by_kook_id(p2_id)
    if not (p1_user and p2_user and p1_user.id and p2_user.id):
        return ''

    from app.extensions import db
    from app.models.minigame import MiniGameRating

    def _ensure_row(user_id):
        row = MiniGameRating.query.filter_by(user_id=user_id, game='blackjack_pvp').first()
        if not row:
            row = MiniGameRating(
                user_id=user_id,
                game='blackjack_pvp',
                rating=BLACKJACK_PVP_DEFAULT_RATING,
                peak_rating=BLACKJACK_PVP_DEFAULT_RATING,
                win_streak=0,
                games_played=0,
            )
            db.session.add(row)
        return row

    row1 = _ensure_row(p1_user.id)
    row2 = _ensure_row(p2_user.id)
    before1 = int(row1.rating or BLACKJACK_PVP_DEFAULT_RATING)
    before2 = int(row2.rating or BLACKJACK_PVP_DEFAULT_RATING)

    expected1 = 1.0 / (1.0 + 10 ** ((before2 - before1) / 400.0))
    expected2 = 1.0 - expected1

    winner_id = str(payload.get('winner_id') or '').strip()
    result = str(payload.get('result') or '')
    if result == 'draw':
        actual1, actual2 = 0.5, 0.5
    elif winner_id == p1_id:
        actual1, actual2 = 1.0, 0.0
    elif winner_id == p2_id:
        actual1, actual2 = 0.0, 1.0
    else:
        actual1, actual2 = 0.5, 0.5

    base_delta1 = int(round(BLACKJACK_PVP_K_FACTOR * (actual1 - expected1)))
    base_delta2 = int(round(BLACKJACK_PVP_K_FACTOR * (actual2 - expected2)))

    is_win1 = actual1 == 1.0
    is_win2 = actual2 == 1.0
    prev_streak1 = int(row1.win_streak or 0)
    prev_streak2 = int(row2.win_streak or 0)
    bonus1 = BLACKJACK_PVP_STREAK_BONUS if (is_win1 and prev_streak1 >= 2) else 0
    bonus2 = BLACKJACK_PVP_STREAK_BONUS if (is_win2 and prev_streak2 >= 2) else 0

    after1 = max(0, before1 + base_delta1 + bonus1)
    after2 = max(0, before2 + base_delta2 + bonus2)
    row1.rating = after1
    row2.rating = after2
    row1.peak_rating = max(int(row1.peak_rating or 0), after1)
    row2.peak_rating = max(int(row2.peak_rating or 0), after2)
    row1.games_played = int(row1.games_played or 0) + 1
    row2.games_played = int(row2.games_played or 0) + 1
    row1.win_streak = prev_streak1 + 1 if is_win1 else 0
    row2.win_streak = prev_streak2 + 1 if is_win2 else 0

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return ''

    return _format_blackjack_pvp_rating_panel(
        players=players,
        before=(before1, before2),
        after=(after1, after2),
        deltas=(base_delta1, base_delta2),
        bonuses=(bonus1, bonus2),
        new_streaks=(int(row1.win_streak), int(row2.win_streak)),
        is_wins=(is_win1, is_win2),
    )


def _format_blackjack_pvp_rating_panel(players, before, after, deltas, bonuses, new_streaks, is_wins):
    sep = '━' * 32
    lines = [sep, '⚔️  **21 点 · 双人对决 · 排位结算**', sep]
    for idx in range(2):
        player = players[idx]
        total_delta = deltas[idx] + bonuses[idx]
        if total_delta > 0:
            change_text = f'`+{total_delta} ▲`'
            score_emoji = '📈'
        elif total_delta < 0:
            change_text = f'`{total_delta} ▼`'
            score_emoji = '📉'
        else:
            change_text = '`±0 ─`'
            score_emoji = '📊'
        tier = blackjack_tier(after[idx])
        tier_emoji = BLACKJACK_TIER_EMOJI.get(tier, '🏅')
        bonus_text = f'　`连胜+{bonuses[idx]}`' if bonuses[idx] else ''
        if is_wins[idx]:
            streak_line = f'  🔥 连胜 ×{new_streaks[idx]}'
        elif new_streaks[idx] == 0 and not is_wins[idx]:
            streak_line = ''
        else:
            streak_line = ''
        block = (
            f'{_player_text(player.get("id") or "")}　{tier_emoji} {tier}\n'
            f'  {score_emoji} {before[idx]} ➜ **{after[idx]}**　{change_text}{bonus_text}'
        )
        if streak_line:
            block += f'\n{streak_line}'
        lines.append(block)
    lines.append(sep)
    return '\n'.join(lines)


def _format_blackjack_pvp_rating_leaderboard(limit=10):
    from app.models.minigame import MiniGameRating
    from app.models.user import User

    limit = max(1, min(50, int(limit or 10)))
    rows = (
        MiniGameRating.query
        .filter_by(game='blackjack_pvp')
        .order_by(
            MiniGameRating.rating.desc(),
            MiniGameRating.peak_rating.desc(),
            MiniGameRating.games_played.asc(),
        )
        .limit(limit)
        .all()
    )

    sep = '━' * 32
    lines = [
        sep,
        '⚔️  **21 点 · 双人对决 · 排位榜 TOP {}**'.format(min(limit, len(rows) or limit)),
        sep,
    ]
    if not rows:
        lines.append('暂无排位记录,先约一局开荒吧。')
        lines.append(sep)
        return '\n'.join(lines)

    user_ids = [int(r.user_id) for r in rows]
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    rank_badges = {1: '🥇', 2: '🥈', 3: '🥉'}
    for idx, r in enumerate(rows, start=1):
        u = users.get(int(r.user_id))
        kook_id = getattr(u, 'kook_id', '') or ''
        mention = _player_text(kook_id) if kook_id else f"**{_display_name_from_user(u, '', kook_id)}**"
        tier = blackjack_tier(int(r.rating or 0))
        tier_emoji = BLACKJACK_TIER_EMOJI.get(tier, '🏅')
        badge = rank_badges.get(idx, f'`#{idx:>2}`')
        lines.append(
            f'{badge}  {mention}　{tier_emoji} **{tier}**　'
            f'`{int(r.rating)}`　巅峰 {int(r.peak_rating or 0)}　· {int(r.games_played or 0)} 局'
        )
    lines.append(sep)
    lines.append(
        '段位 ❯ 🥉 青铜 < 1000　🥈 白银 1000+　🥇 黄金 1200+　'
        '💠 铂金 1400+　💎 钻石 1600+　👑 王者 1800+'
    )
    lines.append(sep)
    return '\n'.join(lines)


# ============================================================
# 数字炸弹（单人 + 多人）
# ============================================================

BOMB_DEFAULT_LOW = 1
BOMB_DEFAULT_HIGH = 100
BOMB_SOLO_MAX_ATTEMPTS = 10
BOMB_MULTI_MIN_PLAYERS = 2
BOMB_MULTI_MAX_PLAYERS = 12


def _bomb_multi_key(channel_id):
    return ('bomb_multi', str(channel_id or 'unknown'))


def _bomb_multi_has_player(session, kook_id):
    if not session or session.game != 'bomb_multi':
        return False
    kook_id = str(kook_id or '').strip()
    if not kook_id:
        return False
    for p in session.state.get('players') or []:
        if str(p.get('id') or '') == kook_id:
            return True
    return False


def _start_bomb_solo(session):
    secret = random.randint(BOMB_DEFAULT_LOW, BOMB_DEFAULT_HIGH)
    session.state = {
        'low': BOMB_DEFAULT_LOW,
        'high': BOMB_DEFAULT_HIGH,
        'secret': secret,
        'attempts_left': BOMB_SOLO_MAX_ATTEMPTS,
        'history': [],
        'finished': False,
        'moves': 0,
    }


def _parse_bomb_number(raw_text, low, high):
    text = str(raw_text or '').strip()
    if not text:
        return None, '请输入一个数字。'
    m = re.search(r'-?\d+', text)
    if not m:
        return None, f'请输入 {low}-{high} 之间的整数。'
    try:
        n = int(m.group(0))
    except ValueError:
        return None, f'请输入 {low}-{high} 之间的整数。'
    if n < low or n > high:
        return None, f'数字必须在当前区间 **{low}-{high}** 内。'
    return n, None


def _guess_bomb_solo(session, guess_text):
    state = session.state
    n, err = _parse_bomb_number(guess_text, state['low'], state['high'])
    if err:
        return _result(err, ok=False)

    state['moves'] = int(state.get('moves') or 0) + 1
    state['attempts_left'] = max(0, int(state['attempts_left']) - 1)
    secret = int(state['secret'])
    history = state.setdefault('history', [])

    if n == secret:
        history.append(f'{n} 命中')
        state['finished'] = True
        record = _build_record_payload(
            session,
            result='win',
            winner_id=session.kook_id,
            winner_name=session.player_name,
            end_reason='solved',
        )
        return _result(
            f'**数字炸弹**\n答案: `{n}`\n用了 **{state["moves"]}** 次猜中，干得漂亮。',
            ended=True,
            record=record,
        )

    if n < secret:
        state['low'] = n + 1
        history.append(f'{n} → 再大一点')
    else:
        state['high'] = n - 1
        history.append(f'{n} → 再小一点')

    if state['attempts_left'] <= 0 or state['low'] > state['high']:
        state['finished'] = True
        record = _build_record_payload(session, result='loss', end_reason='out_of_attempts')
        return _result(
            f'**数字炸弹**\n答案是 `{secret}`。次数用完，本局结束。',
            ended=True,
            record=record,
        )

    return _result(_render_bomb_solo(session))


def _render_bomb_solo(session):
    state = session.state
    history = state.get('history') or []
    history_text = '\n'.join(f'  · {item}' for item in history[-6:]) if history else '  · -'
    return (
        '**数字炸弹**\n'
        f'当前区间: **{state["low"]} - {state["high"]}**\n'
        f'剩余次数: **{state["attempts_left"]}**\n'
        f'历史:\n{history_text}\n'
        '操作: `/游戏 猜 数字` 或直接 `/游戏 数字`'
    )


def start_bomb_multi(channel_id, host_id, host_name):
    """在频道发起多人数字炸弹（招募阶段）。"""
    _cleanup_expired_sessions()
    channel_id = str(channel_id or 'unknown')
    host_id = str(host_id or '').strip()
    if not host_id:
        return _result('未获取到发起人的 KOOK 身份。', ok=False)
    key = _bomb_multi_key(channel_id)
    if _sessions.get(key):
        return _result('当前频道已经有一局多人数字炸弹，先 `/游戏 状态` 看看。', ok=False)
    if _sessions.get(_session_key(channel_id, host_id)):
        return _result('你当前有别的小游戏在进行，请先 `/游戏 退出`。', ok=False)
    if _sessions.get(_undercover_key(channel_id)):
        return _result('当前频道有谁是卧底进行中，无法同时开多人炸弹。', ok=False)

    session = MiniGameSession(
        game='bomb_multi',
        channel_id=channel_id,
        kook_id=host_id,
        player_name=str(host_name or ''),
        state={
            'phase': 'recruiting',
            'host_id': host_id,
            'players': [{'id': host_id, 'name': str(host_name or '')}],
            'low': BOMB_DEFAULT_LOW,
            'high': BOMB_DEFAULT_HIGH,
            'secret': 0,
            'turn': 0,
            'history': [],
            'moves': 0,
        },
    )
    _sessions[key] = session
    return _result(
        '**多人数字炸弹** 招募中（踩到的输）。\n'
        f'{_player_text(host_id)} 发起，区间 1-100。\n'
        '其他玩家用 `/游戏 炸弹 加入` 入局，'
        f'人数到 {BOMB_MULTI_MIN_PLAYERS}+ 后由发起人发 `/游戏 炸弹 开始`。'
    )


def join_bomb_multi(channel_id, kook_id, kook_name):
    session = _sessions.get(_bomb_multi_key(channel_id))
    if not session:
        return _result('当前频道没有招募中的多人数字炸弹。先 `/游戏 炸弹 多人` 发起。', ok=False)
    if session.state.get('phase') != 'recruiting':
        return _result('当前局已经开始，无法再加入。', ok=False)
    kook_id = str(kook_id or '').strip()
    if not kook_id:
        return _result('未获取到你的 KOOK 身份。', ok=False)
    players = session.state.setdefault('players', [])
    if any(str(p.get('id') or '') == kook_id for p in players):
        return _result('你已经在局里了。', ok=False)
    if len(players) >= BOMB_MULTI_MAX_PLAYERS:
        return _result(f'人数已满（{BOMB_MULTI_MAX_PLAYERS}）。', ok=False)
    if _sessions.get(_session_key(session.channel_id, kook_id)):
        return _result('你当前有别的小游戏在进行，请先 `/游戏 退出`。', ok=False)
    players.append({'id': kook_id, 'name': str(kook_name or '')})
    session.touch()
    names = '、'.join(_player_text(p['id']) for p in players)
    return _result(
        f'{_player_text(kook_id)} 已加入。\n当前 **{len(players)}** 人: {names}\n'
        '人数到位后由发起人发 `/游戏 炸弹 开始`。'
    )


def begin_bomb_multi(channel_id, kook_id):
    session = _sessions.get(_bomb_multi_key(channel_id))
    if not session:
        return _result('当前频道没有多人数字炸弹。', ok=False)
    if session.state.get('phase') != 'recruiting':
        return _result('当前局已经开始，发 `/游戏 状态` 看回合。', ok=False)
    if str(session.state.get('host_id') or '') != str(kook_id or ''):
        return _result('只有发起人能开始本局。', ok=False)
    players = session.state.get('players') or []
    if len(players) < BOMB_MULTI_MIN_PLAYERS:
        return _result(f'至少需要 {BOMB_MULTI_MIN_PLAYERS} 人才能开始。', ok=False)

    random.shuffle(players)
    session.state['players'] = players
    session.state['phase'] = 'playing'
    session.state['secret'] = random.randint(BOMB_DEFAULT_LOW, BOMB_DEFAULT_HIGH)
    session.state['turn'] = 0
    session.touch()
    return _result(
        '**多人数字炸弹** 开始！踩到炸弹的输，其他人共赢。\n' + _render_bomb_multi(session)
    )


def _guess_bomb_multi(session, kook_id, guess_text):
    if session.state.get('phase') != 'playing':
        return _result('本局还在招募中，等发起人 `/游戏 炸弹 开始` 再猜。', ok=False)
    players = session.state.get('players') or []
    turn = int(session.state.get('turn') or 0)
    if not players:
        return _result('当前局没有玩家，已结束。', ok=False)
    current_player = players[turn % len(players)]
    if str(current_player.get('id') or '') != str(kook_id or ''):
        return _result(f'还没轮到你。当前: {_player_text(current_player.get("id"))}', ok=False)

    state = session.state
    n, err = _parse_bomb_number(guess_text, state['low'], state['high'])
    if err:
        return _result(err, ok=False)

    state['moves'] = int(state.get('moves') or 0) + 1
    secret = int(state['secret'])
    history = state.setdefault('history', [])

    if n == secret:
        history.append(f'{_short_name(current_player)} 猜 {n} → 💥 踩雷')
        loser_id = str(current_player.get('id') or '')
        loser_name = str(current_player.get('name') or '')
        winners = [p for p in players if str(p.get('id') or '') != loser_id]
        winners_text = '、'.join(_player_text(p['id']) for p in winners) or '无人'
        message = (
            f'**多人数字炸弹** 💥\n'
            f'答案: `{secret}`\n'
            f'踩到炸弹: {_player_text(loser_id)}\n'
            f'共赢: {winners_text}\n'
            f'累计回合: **{state["moves"]}**'
        )
        _sessions.pop(_bomb_multi_key(session.channel_id), None)
        # 多人模式不入排行（多玩家结构 vs 双玩家 schema 难以公平），仅播报。
        return _result(message, ended=True)

    if n < secret:
        state['low'] = n + 1
        history.append(f'{_short_name(current_player)} 猜 {n} → ↑')
    else:
        state['high'] = n - 1
        history.append(f'{_short_name(current_player)} 猜 {n} → ↓')

    state['turn'] = (turn + 1) % len(players)
    session.touch()
    return _result(_render_bomb_multi(session))


def _render_bomb_multi(session):
    state = session.state
    players = state.get('players') or []
    phase = state.get('phase', 'recruiting')
    if phase == 'recruiting':
        roster = '\n'.join(
            f'  {idx + 1}. {_player_text(p["id"])}'
            for idx, p in enumerate(players)
        ) or '  -'
        return (
            '**多人数字炸弹** · 招募中\n'
            f'区间: 1-100\n'
            f'人数: **{len(players)}** / 最少 {BOMB_MULTI_MIN_PLAYERS}\n'
            f'{roster}\n'
            '`/游戏 炸弹 加入` 入局，发起人 `/游戏 炸弹 开始`。'
        )
    turn = int(state.get('turn') or 0)
    current = players[turn % len(players)] if players else {}
    history = state.get('history') or []
    history_text = '\n'.join(f'  · {item}' for item in history[-6:]) if history else '  · -'
    queue = ' → '.join(_short_name(p) for p in players)
    return (
        '**多人数字炸弹** · 进行中\n'
        f'当前区间: **{state["low"]} - {state["high"]}**\n'
        f'当前回合: {_player_text(current.get("id"))}\n'
        f'顺序: {queue}\n'
        f'累计回合: **{state.get("moves") or 0}**\n'
        f'历史:\n{history_text}\n'
        '操作: `/游戏 猜 数字`（轮到你时）；`/游戏 退出` 解散。'
    )


def _bomb_multi_quit(session, kook_id):
    """招募阶段任何人可退；进行中只允许发起人解散。"""
    state = session.state
    phase = state.get('phase', 'recruiting')
    host_id = str(state.get('host_id') or '')
    kook_id = str(kook_id or '')

    if phase == 'recruiting':
        players = state.get('players') or []
        if kook_id == host_id:
            _sessions.pop(_bomb_multi_key(session.channel_id), None)
            return _result(f'已解散 **多人数字炸弹**（发起人 {_player_text(kook_id)} 取消招募）。', ended=True)
        new_players = [p for p in players if str(p.get('id') or '') != kook_id]
        if len(new_players) == len(players):
            return _result('你不在当前招募列表里。', ok=False)
        state['players'] = new_players
        return _result(f'{_player_text(kook_id)} 已退出招募。\n\n' + _render_bomb_multi(session), ended=False)

    if kook_id != host_id:
        return _result('对局已开始，仅发起人可发 `/游戏 退出` 解散。', ok=False)
    _sessions.pop(_bomb_multi_key(session.channel_id), None)
    return _result(f'已解散 **多人数字炸弹**（由 {_player_text(kook_id)} 解散）。', ended=True)


def _short_name(player):
    name = str((player or {}).get('name') or '').strip()
    if name:
        return name.split('#')[0][:10]
    pid = str((player or {}).get('id') or '')
    return pid[-4:] if pid else '玩家'


# ============================================================
# 谁是卧底
# ============================================================

UNDERCOVER_MIN_PLAYERS = 4
UNDERCOVER_MAX_PLAYERS = 8

UNDERCOVER_ROLE_TABLE = {
    4: 1,
    5: 1,
    6: 2,
    7: 2,
    8: 2,
}

UNDERCOVER_FALLBACK_PAIRS = [
    ('咖啡', '奶茶'),
    ('狮子', '老虎'),
    ('孙悟空', '齐天大圣'),
    ('草莓', '樱桃'),
    ('钢琴', '电子琴'),
    ('微波炉', '烤箱'),
    ('警察', '保安'),
    ('医生', '护士'),
    ('蛋糕', '面包'),
    ('泡面', '螺蛳粉'),
    ('啤酒', '香槟'),
    ('地铁', '公交'),
    ('微信', 'QQ'),
    ('鼠标', '触摸板'),
    ('火锅', '麻辣烫'),
    ('哈士奇', '萨摩耶'),
    ('王者荣耀', '英雄联盟'),
    ('CSGO', '无畏契约'),
    ('诸葛亮', '司马懿'),
    ('熊大', '熊二'),
]

UNDERCOVER_LLM_SYSTEM_PROMPT = (
    '你是"谁是卧底"游戏的出题人。生成一对中文词语用于游戏。\n'
    '要求：\n'
    '1. 两词在某个属性上相似但有微妙区别，玩家容易混淆，但描述时能找到差异点；\n'
    '2. 都是日常常见的事物或概念（食物/动物/饮品/明星/影视/职业/物品/游戏 等），不要生僻；\n'
    '3. 不能完全相同，也不能完全无关；\n'
    '4. 内容要适合所有人讨论，不涉及政治/暴力/色情。\n\n'
    '严格只返回一个 JSON 对象，不要任何额外文字：\n'
    '{"civilian": "词A", "undercover": "词B", "category": "类别", "hint": "对比要点"}\n\n'
    '示例：\n'
    '{"civilian": "咖啡", "undercover": "奶茶", "category": "饮品", "hint": "原料/口感"}\n'
    '{"civilian": "孙悟空", "undercover": "齐天大圣", "category": "人物", "hint": "称呼角度"}'
)


def _undercover_key(channel_id):
    return ('undercover', str(channel_id or 'unknown'))


def _undercover_has_player(session, kook_id):
    if not session or session.game != 'undercover':
        return False
    kook_id = str(kook_id or '').strip()
    if not kook_id:
        return False
    for p in session.state.get('players') or []:
        if str(p.get('id') or '') == kook_id:
            return True
    return False


def undercover_menu_text():
    return (
        '**谁是卧底**\n'
        '---\n'
        '`/游戏 卧底 发起` - 在当前频道发起一局\n'
        '`/游戏 卧底 加入` - 加入正在招募的局\n'
        '`/游戏 卧底 开始` - 发起人开始（≥4 人）\n'
        '`/游戏 卧底 描述 内容` - 轮到你时发言（描述但不能直接说出词）\n'
        '`/游戏 卧底 投票 编号` - 投票踢人（编号见状态）\n'
        '`/游戏 卧底 状态` - 查看当前阶段\n'
        '`/游戏 卧底 退出` - 退出 / 发起人解散\n'
        '---\n'
        '规则: 多数平民拿到词A，少数卧底拿到词B（AI 出题）。轮流描述后投票踢出最可疑的人。\n'
        f'人数: {UNDERCOVER_MIN_PLAYERS}-{UNDERCOVER_MAX_PLAYERS} 人。'
    )


def _llm_config(name, default=''):
    try:
        from flask import current_app, has_app_context
        if has_app_context() and name in current_app.config:
            return current_app.config.get(name, default)
    except Exception:
        pass
    return os.environ.get(name, default)


def _normalize_llm_url(api_url):
    url = str(api_url or '').strip().rstrip('/')
    if not url:
        return ''
    if url.endswith('/chat/completions'):
        return url
    if url.endswith('/v1') or url.endswith('/beta'):
        return f'{url}/chat/completions'
    return f'{url}/chat/completions'


def _call_minigame_llm(messages, max_tokens=300, temperature=0.85):
    api_key = _llm_config('STORY_LLM_API_KEY', '')
    api_url = _normalize_llm_url(_llm_config('STORY_LLM_API_URL', ''))
    model = str(_llm_config('STORY_LLM_MODEL', 'deepseek-v4-flash') or 'deepseek-v4-flash').strip()
    if 'api.deepseek.com' in api_url and model in ('', 'deepseek-ai/DeepSeek-V4-Flash', 'DeepSeek-V4-Flash', 'deepseek-chat'):
        model = 'deepseek-v4-flash'
    if not api_key or not api_url:
        return None
    try:
        import requests
        resp = requests.post(
            api_url,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': model,
                'messages': messages,
                'temperature': temperature,
                'max_tokens': max_tokens,
                'response_format': {'type': 'json_object'},
            },
            timeout=int(_llm_config('STORY_LLM_TIMEOUT', 25)),
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        choices = data.get('choices') or []
        if not choices:
            return None
        msg = choices[0].get('message') or {}
        return msg.get('content') or choices[0].get('text')
    except Exception:
        return None


def _generate_undercover_word_pair():
    """LLM 生成词对，失败回退本地词库。返回 (civilian_word, undercover_word, meta)。"""
    user_prompt = (
        '请直接生成一对全新的词，类别不限。'
        f'\n随机种子: {random.randint(1000, 9999)}（确保多样性）。'
    )
    messages = [
        {'role': 'system', 'content': UNDERCOVER_LLM_SYSTEM_PROMPT},
        {'role': 'user', 'content': user_prompt},
    ]
    raw = _call_minigame_llm(messages)
    if raw:
        try:
            obj = json.loads(raw)
            civilian = str(obj.get('civilian') or '').strip()
            undercover = str(obj.get('undercover') or '').strip()
            if civilian and undercover and civilian != undercover and len(civilian) <= 12 and len(undercover) <= 12:
                return civilian, undercover, {
                    'source': 'llm',
                    'category': str(obj.get('category') or '').strip(),
                    'hint': str(obj.get('hint') or '').strip(),
                }
        except Exception:
            pass
    pair = random.choice(UNDERCOVER_FALLBACK_PAIRS)
    civilian, undercover = pair if random.random() < 0.5 else (pair[1], pair[0])
    return civilian, undercover, {'source': 'fallback', 'category': '', 'hint': ''}


def create_undercover(channel_id, host_id, host_name):
    """发起一局谁是卧底（招募阶段）。"""
    _cleanup_expired_sessions()
    channel_id = str(channel_id or 'unknown')
    host_id = str(host_id or '').strip()
    if not host_id:
        return _result('未获取到发起人的 KOOK 身份。', ok=False)
    key = _undercover_key(channel_id)
    if _sessions.get(key):
        return _result('当前频道已有谁是卧底，先 `/游戏 卧底 状态` 查看。', ok=False)
    if _sessions.get(_session_key(channel_id, host_id)):
        return _result('你当前有别的小游戏在进行，请先 `/游戏 退出`。', ok=False)
    if _sessions.get(_bomb_multi_key(channel_id)):
        return _result('当前频道有多人炸弹进行中。', ok=False)

    session = MiniGameSession(
        game='undercover',
        channel_id=channel_id,
        kook_id=host_id,
        player_name=str(host_name or ''),
        state={
            'phase': 'recruiting',
            'host_id': host_id,
            'players': [_undercover_new_player(host_id, host_name)],
            'civilian_word': '',
            'undercover_word': '',
            'word_meta': {},
            'round': 0,
            'turn_index': 0,
            'descriptions': [],
            'votes': {},
            'eliminated': [],
            'result': '',
        },
    )
    _sessions[key] = session
    return _result(
        '**谁是卧底** 招募中。\n'
        f'{_player_text(host_id)} 发起。\n'
        f'其他人 `/游戏 卧底 加入`，凑到 **{UNDERCOVER_MIN_PLAYERS}-{UNDERCOVER_MAX_PLAYERS}** 人后由发起人 `/游戏 卧底 开始`。\n'
        '词对由 AI 生成（失败时回退本地词库）。'
    )


def _undercover_new_player(kook_id, name):
    return {
        'id': str(kook_id or ''),
        'name': str(name or ''),
        'role': '',
        'word': '',
        'alive': True,
        'eliminated_round': None,
    }


def join_undercover(channel_id, kook_id, kook_name):
    session = _sessions.get(_undercover_key(channel_id))
    if not session:
        return _result('当前频道没有招募中的谁是卧底。先 `/游戏 卧底 发起`。', ok=False)
    if session.state.get('phase') != 'recruiting':
        return _result('对局已开始，无法加入。', ok=False)
    kook_id = str(kook_id or '').strip()
    if not kook_id:
        return _result('未获取到你的 KOOK 身份。', ok=False)
    players = session.state.setdefault('players', [])
    if any(str(p.get('id') or '') == kook_id for p in players):
        return _result('你已经在局里了。', ok=False)
    if len(players) >= UNDERCOVER_MAX_PLAYERS:
        return _result(f'人数已满（{UNDERCOVER_MAX_PLAYERS}）。', ok=False)
    if _sessions.get(_session_key(session.channel_id, kook_id)):
        return _result('你当前有别的小游戏在进行，请先 `/游戏 退出`。', ok=False)
    players.append(_undercover_new_player(kook_id, kook_name))
    session.touch()
    return _result(
        f'{_player_text(kook_id)} 已加入。\n'
        f'当前 **{len(players)}** / {UNDERCOVER_MIN_PLAYERS}-{UNDERCOVER_MAX_PLAYERS} 人。\n\n'
        + _render_undercover(session)
    )


def begin_undercover(channel_id, kook_id):
    session = _sessions.get(_undercover_key(channel_id))
    if not session:
        return _result('当前频道没有谁是卧底。', ok=False)
    if session.state.get('phase') != 'recruiting':
        return _result('对局已开始。`/游戏 卧底 状态` 查看进度。', ok=False)
    if str(session.state.get('host_id') or '') != str(kook_id or ''):
        return _result('只有发起人能开始本局。', ok=False)
    players = session.state.get('players') or []
    if len(players) < UNDERCOVER_MIN_PLAYERS:
        return _result(f'至少需要 {UNDERCOVER_MIN_PLAYERS} 人。', ok=False)
    if len(players) > UNDERCOVER_MAX_PLAYERS:
        return _result(f'人数超过上限 {UNDERCOVER_MAX_PLAYERS}。', ok=False)

    civilian_word, undercover_word, meta = _generate_undercover_word_pair()
    undercover_count = UNDERCOVER_ROLE_TABLE.get(len(players), 1)

    indices = list(range(len(players)))
    random.shuffle(indices)
    undercover_indices = set(indices[:undercover_count])

    dm_targets = []
    for idx, player in enumerate(players):
        if idx in undercover_indices:
            player['role'] = 'undercover'
            player['word'] = undercover_word
        else:
            player['role'] = 'civilian'
            player['word'] = civilian_word
        player['alive'] = True
        player['eliminated_round'] = None
        dm_targets.append({
            'kook_id': player['id'],
            'text': (
                f'**谁是卧底** 你的身份已生成。\n'
                f'你的词: `{player["word"]}`\n'
                f'回到频道用 `/游戏 卧底 描述 内容` 描述这个词，但不能直接说出。\n'
                '提示: 描述既不能太露骨被卧底偷词，也不能太离谱被怀疑。'
            ),
        })

    random.shuffle(players)
    session.state['players'] = players
    session.state['civilian_word'] = civilian_word
    session.state['undercover_word'] = undercover_word
    session.state['word_meta'] = meta
    session.state['phase'] = 'describing'
    session.state['round'] = 1
    session.state['turn_index'] = 0
    session.state['descriptions'] = []
    session.state['votes'] = {}
    session.state['eliminated'] = []
    session.touch()

    source_label = 'AI 生成' if meta.get('source') == 'llm' else '本地词库'
    return _result(
        f'**谁是卧底** 开始！本局共 {len(players)} 人，其中 {undercover_count} 个卧底。\n'
        f'词对来源: {source_label}。请查看私信确认你的词。\n\n'
        + _render_undercover(session),
        side_effects={'dm': dm_targets},
    )


def describe_undercover(channel_id, kook_id, text):
    session = _sessions.get(_undercover_key(channel_id))
    if not session:
        return _result('当前频道没有谁是卧底。', ok=False)
    if session.state.get('phase') != 'describing':
        return _result('当前不是描述阶段。`/游戏 卧底 状态` 查看。', ok=False)
    text = str(text or '').strip()
    if not text:
        return _result('请发送描述内容: `/游戏 卧底 描述 内容`。', ok=False)
    if len(text) > 80:
        return _result('描述请不超过 80 字。', ok=False)

    alive_players = _undercover_alive_players(session)
    turn = int(session.state.get('turn_index') or 0)
    if not alive_players:
        return _result('当前没有存活玩家。', ok=False)
    current = alive_players[turn % len(alive_players)]
    if str(current.get('id') or '') != str(kook_id or ''):
        return _result(f'还没轮到你。当前发言: {_player_text(current.get("id"))}', ok=False)

    civilian_word = session.state.get('civilian_word', '')
    undercover_word = session.state.get('undercover_word', '')
    if civilian_word and civilian_word in text:
        return _result(f'描述里不能包含 `{civilian_word}` 本身，换个说法。', ok=False)
    if undercover_word and undercover_word in text:
        return _result(f'描述里不能包含 `{undercover_word}` 本身，换个说法。', ok=False)

    descriptions = session.state.setdefault('descriptions', [])
    descriptions.append({
        'round': int(session.state.get('round') or 1),
        'player_id': str(current.get('id') or ''),
        'name': str(current.get('name') or ''),
        'text': text,
    })

    session.state['turn_index'] = turn + 1
    if session.state['turn_index'] >= len(alive_players):
        session.state['phase'] = 'voting'
        session.state['votes'] = {}
        session.state['turn_index'] = 0
        session.touch()
        return _result(
            f'{_player_text(current.get("id"))} 描述: {text}\n\n'
            '本轮描述结束，进入投票。\n\n' + _render_undercover(session)
        )
    session.touch()
    next_player = alive_players[session.state['turn_index'] % len(alive_players)]
    return _result(
        f'{_player_text(current.get("id"))} 描述: {text}\n\n'
        f'下一位: {_player_text(next_player.get("id"))}\n'
        '使用 `/游戏 卧底 描述 内容`。'
    )


def vote_undercover(channel_id, kook_id, target_text):
    session = _sessions.get(_undercover_key(channel_id))
    if not session:
        return _result('当前频道没有谁是卧底。', ok=False)
    if session.state.get('phase') != 'voting':
        return _result('当前不是投票阶段。`/游戏 卧底 状态` 查看。', ok=False)

    voter = _undercover_player_by_id(session, kook_id)
    if not voter or not voter.get('alive'):
        return _result('你不在本局或已经出局，不能投票。', ok=False)

    target = _undercover_resolve_vote_target(session, target_text)
    if not target:
        return _result(
            '无法识别投票目标。可用 `/游戏 卧底 投票 编号`，编号见 `/游戏 卧底 状态`。',
            ok=False,
        )
    if str(target.get('id')) == str(voter.get('id')):
        return _result('不能投自己。', ok=False)

    votes = session.state.setdefault('votes', {})
    votes[str(voter['id'])] = str(target['id'])
    session.touch()

    alive = _undercover_alive_players(session)
    voted_count = sum(1 for p in alive if str(p['id']) in votes)
    if voted_count < len(alive):
        return _result(
            f'{_player_text(voter["id"])} 投给了 {_player_text(target["id"])}。\n'
            f'已投: **{voted_count}** / {len(alive)}',
        )

    return _undercover_resolve_round(session)


def _undercover_resolve_round(session):
    alive = _undercover_alive_players(session)
    votes = session.state.get('votes') or {}
    tallies = {}
    for target_id in votes.values():
        tallies[target_id] = tallies.get(target_id, 0) + 1

    if not tallies:
        return _result('本轮没有有效投票，跳过踢人。', ok=False)

    top = max(tallies.values())
    candidates = [pid for pid, n in tallies.items() if n == top]
    if len(candidates) > 1:
        eliminated_id = random.choice(candidates)
        tie_text = '（票数相同，随机抽中）'
    else:
        eliminated_id = candidates[0]
        tie_text = ''

    eliminated = _undercover_player_by_id(session, eliminated_id)
    if not eliminated:
        return _result('投票出现异常，本轮无人出局。', ok=False)

    eliminated['alive'] = False
    eliminated['eliminated_round'] = int(session.state.get('round') or 1)
    session.state.setdefault('eliminated', []).append(str(eliminated_id))

    tally_lines = '\n'.join(
        f'  · {_player_text(pid)}: {n} 票' for pid, n in sorted(tallies.items(), key=lambda x: -x[1])
    )
    role_label = '卧底' if eliminated.get('role') == 'undercover' else '平民'
    role_emoji = '🕵️' if eliminated.get('role') == 'undercover' else '👥'
    civilian_word = session.state.get('civilian_word', '')
    undercover_word = session.state.get('undercover_word', '')

    end_state = _undercover_check_winner(session)
    if end_state:
        winner_side = end_state
        winners = [p for p in session.state.get('players') or [] if p.get('role') == winner_side]
        winner_names = '、'.join(_player_text(p['id']) for p in winners)
        winner_label = '平民' if winner_side == 'civilian' else '卧底'
        message = (
            '**谁是卧底** · 投票揭晓\n'
            f'{tally_lines}\n'
            f'被踢出: {_player_text(eliminated_id)} → {role_emoji} **{role_label}** {tie_text}\n'
            f'\n🏁 **{winner_label}阵营获胜**！\n'
            f'平民词: `{civilian_word}`　卧底词: `{undercover_word}`\n'
            f'获胜玩家: {winner_names}'
        )
        _sessions.pop(_undercover_key(session.channel_id), None)
        session.state['phase'] = 'ended'
        session.state['result'] = winner_side
        return _result(message, ended=True)

    session.state['round'] = int(session.state.get('round') or 1) + 1
    session.state['phase'] = 'describing'
    session.state['turn_index'] = 0
    session.state['votes'] = {}
    session.touch()

    return _result(
        '**谁是卧底** · 投票揭晓\n'
        f'{tally_lines}\n'
        f'被踢出: {_player_text(eliminated_id)} → {role_emoji} **{role_label}** {tie_text}\n\n'
        f'进入第 {session.state["round"]} 轮描述。\n\n'
        + _render_undercover(session)
    )


def _undercover_check_winner(session):
    """返回 'civilian' 或 'undercover' 表示阵营获胜；None 表示继续。"""
    players = session.state.get('players') or []
    alive_civilian = sum(1 for p in players if p.get('alive') and p.get('role') == 'civilian')
    alive_undercover = sum(1 for p in players if p.get('alive') and p.get('role') == 'undercover')
    if alive_undercover == 0:
        return 'civilian'
    if alive_undercover >= alive_civilian:
        return 'undercover'
    return None


def _undercover_alive_players(session):
    return [p for p in (session.state.get('players') or []) if p.get('alive')]


def _undercover_player_by_id(session, kook_id):
    kook_id = str(kook_id or '').strip()
    for p in session.state.get('players') or []:
        if str(p.get('id') or '') == kook_id:
            return p
    return None


def _undercover_resolve_vote_target(session, target_text):
    """支持编号 / @mention / kook_id 数字。仅返回 alive 玩家。"""
    raw = str(target_text or '').strip()
    if not raw:
        return None
    alive = _undercover_alive_players(session)
    digit_match = re.search(r'\d+', raw)
    if digit_match:
        n = int(digit_match.group(0))
        if 1 <= n <= len(alive):
            return alive[n - 1]
        for p in alive:
            if str(p.get('id') or '') == str(n):
                return p
    mention_match = re.search(r'\(met\)(\d+)\(met\)|<@!?(\d+)>', raw)
    if mention_match:
        kook_id = mention_match.group(1) or mention_match.group(2)
        for p in alive:
            if str(p.get('id') or '') == str(kook_id):
                return p
    return None


def _render_undercover(session):
    state = session.state
    phase = state.get('phase', 'recruiting')
    players = state.get('players') or []
    if phase == 'recruiting':
        lines = [
            '**谁是卧底** · 招募中',
            f'人数: **{len(players)}** / {UNDERCOVER_MIN_PLAYERS}-{UNDERCOVER_MAX_PLAYERS}',
        ]
        for idx, p in enumerate(players, start=1):
            lines.append(f'  {idx}. {_player_text(p["id"])}')
        lines.append('')
        lines.append('`/游戏 卧底 加入` 入局，发起人 `/游戏 卧底 开始`。')
        return '\n'.join(lines)

    alive = _undercover_alive_players(session)
    eliminated = [p for p in players if not p.get('alive')]

    lines = [f'**谁是卧底** · 第 {state.get("round", 1)} 轮 · {("描述阶段" if phase == "describing" else "投票阶段")}']

    lines.append('存活玩家:')
    for idx, p in enumerate(alive, start=1):
        lines.append(f'  {idx}. {_player_text(p["id"])}')

    if eliminated:
        lines.append('已出局:')
        for p in eliminated:
            role_label = '卧底' if p.get('role') == 'undercover' else '平民'
            lines.append(f'  · {_player_text(p["id"])} ({role_label})')

    descriptions = state.get('descriptions') or []
    cur_round = int(state.get('round') or 1)
    cur_round_desc = [d for d in descriptions if d.get('round') == cur_round]
    if cur_round_desc:
        lines.append('本轮描述:')
        for d in cur_round_desc:
            lines.append(f'  · {_player_text(d["player_id"])}: {d["text"]}')

    if phase == 'describing':
        turn = int(state.get('turn_index') or 0)
        if alive:
            current = alive[turn % len(alive)]
            lines.append('')
            lines.append(f'轮到: {_player_text(current["id"])}')
            lines.append('操作: `/游戏 卧底 描述 内容`（一句话，不能含词本身）')
    elif phase == 'voting':
        votes = state.get('votes') or {}
        voted = sum(1 for p in alive if str(p['id']) in votes)
        lines.append('')
        lines.append(f'投票进度: **{voted}** / {len(alive)}')
        lines.append('操作: `/游戏 卧底 投票 编号`（编号取上方"存活玩家"列表）')

    return '\n'.join(lines)


def _undercover_quit(session, kook_id):
    """招募阶段任何人可退；进行中只允许发起人解散。"""
    state = session.state
    phase = state.get('phase', 'recruiting')
    host_id = str(state.get('host_id') or '')
    kook_id = str(kook_id or '')

    if phase == 'recruiting':
        if kook_id == host_id:
            _sessions.pop(_undercover_key(session.channel_id), None)
            return _result(f'已解散 **谁是卧底**（{_player_text(kook_id)} 取消招募）。', ended=True)
        players = state.get('players') or []
        new_players = [p for p in players if str(p.get('id') or '') != kook_id]
        if len(new_players) == len(players):
            return _result('你不在当前招募列表里。', ok=False)
        state['players'] = new_players
        return _result(f'{_player_text(kook_id)} 已退出。\n\n' + _render_undercover(session))

    if kook_id != host_id:
        return _result('对局已开始，仅发起人可发 `/游戏 退出` 解散。', ok=False)
    civilian_word = state.get('civilian_word', '')
    undercover_word = state.get('undercover_word', '')
    _sessions.pop(_undercover_key(session.channel_id), None)
    return _result(
        f'已解散 **谁是卧底**（由 {_player_text(kook_id)} 解散）。\n'
        f'平民词: `{civilian_word}`　卧底词: `{undercover_word}`',
        ended=True,
    )


def handle_undercover_command(channel_id, kook_id, kook_name, action, rest):
    """谁是卧底命令统一入口。action 已 lower。"""
    action = str(action or '').strip().lower()
    if action in ('', '帮助', 'help', '菜单'):
        return _result(undercover_menu_text())
    if action in ('发起', '开局', '创建', 'create', 'new'):
        return create_undercover(channel_id, kook_id, kook_name)
    if action in ('加入', 'join'):
        return join_undercover(channel_id, kook_id, kook_name)
    if action in ('开始', 'start', 'begin'):
        return begin_undercover(channel_id, kook_id)
    if action in ('描述', '发言', 'desc', 'describe'):
        return describe_undercover(channel_id, kook_id, rest)
    if action in ('投票', '投', 'vote'):
        return vote_undercover(channel_id, kook_id, rest)
    if action in ('状态', 'status'):
        session = _sessions.get(_undercover_key(channel_id))
        if not session:
            return _result('当前频道没有谁是卧底。', ok=False)
        return _result(_render_undercover(session))
    if action in ('退出', '解散', 'quit', 'stop', 'cancel'):
        session = _sessions.get(_undercover_key(channel_id))
        if not session:
            return _result('当前频道没有谁是卧底。', ok=False)
        return _undercover_quit(session, kook_id)
    return _result(f'不认识的指令 `{action}`。\n\n' + undercover_menu_text(), ok=False)


def handle_bomb_command(channel_id, kook_id, kook_name, action, rest):
    """数字炸弹命令统一入口。"""
    action = str(action or '').strip().lower()
    if action in ('', '单人', 'solo'):
        return start_game(channel_id, kook_id, kook_name, 'bomb')
    if action in ('多人', 'multi', '多人模式', '接力'):
        return start_bomb_multi(channel_id, kook_id, kook_name)
    if action in ('加入', 'join'):
        return join_bomb_multi(channel_id, kook_id, kook_name)
    if action in ('开始', 'start', 'begin'):
        return begin_bomb_multi(channel_id, kook_id)
    if action in ('状态', 'status'):
        bomb_multi = _sessions.get(_bomb_multi_key(channel_id))
        if bomb_multi and _bomb_multi_has_player(bomb_multi, kook_id):
            return _result(_render_bomb_multi(bomb_multi))
        solo = _sessions.get(_session_key(channel_id, kook_id))
        if solo and solo.game == 'bomb':
            return _result(_render_bomb_solo(solo))
        return _result('当前没有进行中的数字炸弹。', ok=False)
    if action in ('退出', 'quit', 'stop', 'cancel'):
        return quit_game(channel_id, kook_id)
    if action in ('帮助', 'help', '菜单'):
        return _result(
            '**数字炸弹**\n'
            '`/游戏 炸弹` 单人速通（10 次内猜中 1-100）\n'
            '`/游戏 炸弹 多人` 多人接力（踩到的输）\n'
            '`/游戏 炸弹 加入` / `开始` / `状态` / `退出`\n'
            '猜数字: `/游戏 猜 50` 或 `/游戏 50`'
        )
    return _result(f'不认识的指令 `{action}`。\n用 `/游戏 炸弹 帮助` 查看说明。', ok=False)
