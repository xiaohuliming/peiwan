"""节日特效查询服务。

后台首次访问对应节假日窗口时触发一次性特效。
节日窗口按"假期前 1-2 天 → 假期结束 +1 天"覆盖，每个 key 含年份，localStorage 按 key 去重。

农历节日（春节/端午/七夕/中秋）的对应公历日期用查表方式，覆盖到 2030。
到期前补充新年表即可，无需引入农历计算依赖。
"""
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Holiday:
    key: str
    name: str
    theme: str
    start: date
    end: date
    title: str
    subtitle: str


def _r(start: date, before: int, after: int) -> tuple:
    """以核心日期为中心生成 [start - before, start + after] 窗口。"""
    return (start - timedelta(days=before), start + timedelta(days=after))


# 农历节日的公历对照（春节/端午/七夕/中秋），到 2030。续表把新年份加进来即可。
_LUNAR_DATES = {
    'spring_festival': {  # 农历正月初一
        2026: date(2026, 2, 17),
        2027: date(2027, 2, 6),
        2028: date(2028, 1, 26),
        2029: date(2029, 2, 13),
        2030: date(2030, 2, 3),
    },
    'dragon_boat': {  # 农历五月初五
        2026: date(2026, 6, 19),
        2027: date(2027, 6, 9),
        2028: date(2028, 5, 27),
        2029: date(2029, 6, 16),
        2030: date(2030, 6, 5),
    },
    'qixi': {  # 农历七月初七
        2026: date(2026, 8, 19),
        2027: date(2027, 8, 8),
        2028: date(2028, 8, 26),
        2029: date(2029, 8, 16),
        2030: date(2030, 8, 5),
    },
    'mid_autumn': {  # 农历八月十五
        2026: date(2026, 9, 25),
        2027: date(2027, 9, 15),
        2028: date(2028, 10, 3),
        2029: date(2029, 9, 22),
        2030: date(2030, 9, 12),
    },
}


def _build_holidays_for_year(year: int) -> list:
    items = []

    # 元旦：跨年窗口（前年 12-31 ~ 当年 1-2）
    s, e = _r(date(year, 1, 1), before=1, after=1)
    items.append(Holiday(
        key=f'new_year_{year}', name='元旦', theme='new_year',
        start=s, end=e,
        title='新年快乐', subtitle=f'迎接 {year} · 来年顺遂',
    ))

    # 春节：核心日 -1 到 +6
    if year in _LUNAR_DATES['spring_festival']:
        cf = _LUNAR_DATES['spring_festival'][year]
        s, e = _r(cf, before=1, after=6)
        items.append(Holiday(
            key=f'spring_festival_{year}', name='春节', theme='spring_festival',
            start=s, end=e,
            title='新春快乐', subtitle='财源广进 · 万事如意',
        ))

    # 劳动节：5-1 ~ 5-5
    items.append(Holiday(
        key=f'labor_day_{year}', name='劳动节', theme='labor_day',
        start=date(year, 5, 1), end=date(year, 5, 5),
        title='五一快乐', subtitle='劳动光荣 · 奋斗不息',
    ))

    # 端午：核心日 -1 到 +2
    if year in _LUNAR_DATES['dragon_boat']:
        db = _LUNAR_DATES['dragon_boat'][year]
        s, e = _r(db, before=1, after=2)
        items.append(Holiday(
            key=f'dragon_boat_{year}', name='端午节', theme='dragon_boat',
            start=s, end=e,
            title='端午安康', subtitle='粽叶飘香 · 龙舟竞渡',
        ))

    # 七夕（非法定，单日触发，前后各 1 天）
    if year in _LUNAR_DATES['qixi']:
        qx = _LUNAR_DATES['qixi'][year]
        s, e = _r(qx, before=0, after=1)
        items.append(Holiday(
            key=f'qixi_{year}', name='七夕', theme='qixi',
            start=s, end=e,
            title='七夕节快乐', subtitle='星河相会 · 心愿成双',
        ))

    # 中秋：核心日 -1 到 +2
    if year in _LUNAR_DATES['mid_autumn']:
        ma = _LUNAR_DATES['mid_autumn'][year]
        s, e = _r(ma, before=1, after=2)
        items.append(Holiday(
            key=f'mid_autumn_{year}', name='中秋节', theme='mid_autumn',
            start=s, end=e,
            title='中秋快乐', subtitle='花好月圆 · 阖家团聚',
        ))

    # 国庆：10-1 ~ 10-7
    items.append(Holiday(
        key=f'national_day_{year}', name='国庆节', theme='national_day',
        start=date(year, 10, 1), end=date(year, 10, 7),
        title=f'国庆快乐', subtitle=f'盛世华诞 · 山河无恙',
    ))

    # 万圣节（非法定，10-31）
    items.append(Holiday(
        key=f'halloween_{year}', name='万圣节', theme='halloween',
        start=date(year, 10, 30), end=date(year, 11, 1),
        title='Trick or Treat', subtitle='不给糖就捣蛋',
    ))

    # 圣诞节（非法定，前夜 + 当日 + 节礼日）
    items.append(Holiday(
        key=f'christmas_{year}', name='圣诞节', theme='christmas',
        start=date(year, 12, 24), end=date(year, 12, 26),
        title='Merry Christmas', subtitle='平安喜乐 · 礼物满满',
    ))

    return items


# 一次性构建索引：当前年和下一年都会被用到（跨年节日如元旦）
_SUPPORTED_YEARS = (2026, 2027, 2028, 2029, 2030, 2031)
_ALL_HOLIDAYS = []
for _y in _SUPPORTED_YEARS:
    _ALL_HOLIDAYS.extend(_build_holidays_for_year(_y))


def get_today_holiday(today: date = None) -> dict:
    """返回今天落在哪个节日窗口里；未命中返回空 dict。"""
    today = today or date.today()
    for h in _ALL_HOLIDAYS:
        if h.start <= today <= h.end:
            return {
                'key': h.key,
                'name': h.name,
                'theme': h.theme,
                'title': h.title,
                'subtitle': h.subtitle,
                'start': h.start.isoformat(),
                'end': h.end.isoformat(),
            }
    return {}
