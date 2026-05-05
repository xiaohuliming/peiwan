"""KOOK 中文文本小游戏。"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
        '`/游戏 四子棋` - 双人四子棋\n'
        '`/游戏 排行 [游戏名]` - 查看排行榜,可填 四子棋/猜词/21点\n'
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
    if game not in {'hangman', 'scramble', 'mastermind', 'blackjack'}:
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
    _sessions[key] = session
    return _result(f'已开启 **{_game_label(game)}**。\n\n{_render_session(session)}')


def get_status(channel_id, kook_id):
    _cleanup_expired_sessions()
    session = _sessions.get(_session_key(channel_id, kook_id))
    if not session:
        connect4_session = _find_connect4_session(channel_id, kook_id) or _sessions.get(_connect4_key(channel_id))
        if connect4_session:
            connect4_session.touch()
            return _result(_render_connect4(connect4_session))
        return _result('你当前没有进行中的小游戏。\n\n' + menu_text(), ok=False)
    session.touch()
    return _result(_render_session(session))


def quit_game(channel_id, kook_id):
    session = _sessions.pop(_session_key(channel_id, kook_id), None)
    if not session:
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
    if not session:
        return _result('你当前没有进行中的猜谜类小游戏。先发送 `/游戏 猜词`、`/游戏 乱序` 或 `/游戏 密码`。', ok=False)

    session.touch()
    if session.game == 'hangman':
        result = _guess_hangman(session, guess_text)
    elif session.game == 'scramble':
        result = _guess_scramble(session, guess_text)
    elif session.game == 'mastermind':
        result = _guess_mastermind(session, guess_text)
    else:
        return _result('21 点不用 `/游戏 猜`，请使用 `/游戏 要牌` 或 `/游戏 停牌`。', ok=False)

    if result.get('ended'):
        _sessions.pop(key, None)
    return result


def handle_blackjack_action(channel_id, kook_id, action):
    _cleanup_expired_sessions()
    key = _session_key(channel_id, kook_id)
    session = _sessions.get(key)
    if not session or session.game != 'blackjack':
        return _result('你当前没有进行中的 21 点。先发送 `/游戏 21点`。', ok=False)

    session.touch()
    action_key = str(action or '').strip().lower()
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

    real_delta = after - before
    sign = '+' if real_delta >= 0 else ''
    bonus_tag = ' 🔥连胜+5' if streak_bonus else ''
    streak_tag = f' · 连胜 {new_streak}' if is_win and new_streak >= 2 else ''
    return f'排位分: {before} → {after} ({sign}{real_delta}){bonus_tag} · {blackjack_tier(after)}{streak_tag}'


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
    lines = ['**21 点排位榜**']
    if not rows:
        lines.append('暂无排位记录,先来一局吧。')
        return '\n'.join(lines)

    user_ids = [int(r.user_id) for r in rows]
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()} if user_ids else {}
    for idx, r in enumerate(rows, start=1):
        u = users.get(int(r.user_id))
        kook_id = getattr(u, 'kook_id', '') or ''
        if kook_id:
            mention = _player_text(kook_id)
        else:
            mention = f"**{_display_name_from_user(u, '', kook_id)}**"
        tier = blackjack_tier(int(r.rating or 0))
        lines.append(
            f'`#{idx}` {mention} **{int(r.rating)}** ({tier}) '
            f'· 巅峰 {int(r.peak_rating or 0)} · {int(r.games_played or 0)} 局'
        )
    lines.append('---')
    lines.append('段位: 青铜 < 1000 / 白银 1000+ / 黄金 1200+ / 铂金 1400+ / 钻石 1600+ / 王者 1800+')
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
        available = '猜词、乱序词、密码色、21点、四子棋'
        return f'暂不支持 `{raw_game}` 的排行榜。可用游戏: {available}。'

    if game == 'blackjack':
        return _format_blackjack_rating_leaderboard(limit)

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


def _result(message, ok=True, ended=False, record=None):
    payload = {'ok': ok, 'message': message, 'ended': ended}
    if record:
        payload['record'] = record
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
    players = session.state.get('players') if session.game == 'connect4' else None
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


def _game_label(game):
    return {
        'hangman': '猜词',
        'scramble': '乱序词',
        'mastermind': '密码色',
        'blackjack': '21 点',
        'connect4': '四子棋',
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
    dealer_value = _hand_value(state['dealer']) if finished else _hand_value([state['dealer'][0]])
    lines = [
        '**21 点**',
        f'庄家: `{dealer_cards}` = **{dealer_value}**' + ('' if finished else ' + 暗牌'),
        f'你: `{player_cards}` = **{_hand_value(state["player"])}**',
    ]
    if not finished:
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
    return menu_text()
