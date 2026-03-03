from app import create_app, db
from app.models.user import User
from app.models.order import Order
from app.models.project import Project, ProjectItem
from app.models.finance import BalanceLog, CommissionLog
from app.models.gift import Gift, GiftOrder
from app.models.intimacy import Intimacy
from app.models.vip import VipLevel, UpgradeRecord
from app.models.broadcast import BroadcastConfig
from app.services.order_service import generate_order_no
from datetime import datetime, timedelta
from decimal import Decimal
import random
import json

app = create_app()


def init_data():
    with app.app_context():
        print("Starting data initialization...")

        # ======== 用户 ========
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', role='superadmin', nickname='高级管理员',
                         kook_id='admin_kook', kook_username='Admin#0001')
            admin.set_password('123456789')
            db.session.add(admin)
            print("Created admin user.")

        staff1 = User.query.filter_by(username='staff1').first()
        if not staff1:
            staff1 = User(username='staff1', role='staff', nickname='客服小美',
                          kook_id='staff1_kook', kook_username='小美#1234')
            staff1.set_password('123456789')
            db.session.add(staff1)
            print("Created staff user: staff1")

        staff2 = User.query.filter_by(username='staff2').first()
        if not staff2:
            staff2 = User(username='staff2', role='staff', nickname='客服小龙',
                          kook_id='staff2_kook', kook_username='小龙#5678')
            staff2.set_password('123456789')
            db.session.add(staff2)
            print("Created staff user: staff2")

        # 陪玩
        players = []
        player_names = ['小软软', 'Kiko', '阿杰', '甜梦', 'Sirus_Fans']
        for i, name in enumerate(player_names):
            p = User.query.filter_by(username=f'player{i}').first()
            if not p:
                p = User(
                    username=f'player{i}', role='player',
                    nickname=f'User_{i}', player_nickname=name,
                    user_code=f'用户{str(i + 1).zfill(5)}',
                    kook_id=f'player{i}_kook',
                    m_bean=Decimal(str(random.randint(100, 5000))),
                    vip_level='GOD'
                )
                p.set_password('123456789')
                db.session.add(p)
                players.append(p)
                print(f"Created player: {name}")
            else:
                players.append(p)

        # 老板
        gods = []
        god_names = ['星空下的猫', '深夜emo', '不吃香菜', 'RichMan', 'GamerPro']
        god_kook = ['星空猫#1111', 'emo#2222', '香菜#3333', 'Rich#4444', 'GPro#5555']
        for i, name in enumerate(god_names):
            g = User.query.filter_by(username=f'god{i}').first()
            if not g:
                g = User(
                    username=f'god{i}', role='god', nickname=name,
                    kook_id=f'god{i}_kook', kook_username=god_kook[i],
                    m_coin=Decimal(str(random.randint(5000, 50000))),
                    vip_level=random.choice(['GOD', 'VIP1', 'VIP2']),
                    vip_discount=Decimal(str(random.choice([100, 95, 90])))
                )
                g.set_password('123456789')
                db.session.add(g)
                gods.append(g)
                print(f"Created god: {name}")
            else:
                gods.append(g)

        db.session.commit()

        # ======== 游戏项目 & 子项目 ========
        if Project.query.count() == 0:
            print("Creating game projects...")

            projects_data = [
                {
                    'name': '三角洲行动', 'sort_order': 1,
                    'items': [
                        {'name': '娱乐陪玩', 'casual': 30, 'tech': 50, 'god': 80, 'pro': 120, 'type': 'normal', 'billing': 'hour'},
                        {'name': '上分车队', 'casual': 40, 'tech': 60, 'god': 100, 'pro': 150, 'type': 'normal', 'billing': 'hour'},
                        {'name': '护航代打', 'casual': 50, 'tech': 80, 'god': 120, 'pro': 180, 'type': 'escort', 'billing': 'hour'},
                    ]
                },
                {
                    'name': '瓦罗兰特', 'sort_order': 2,
                    'items': [
                        {'name': '娱乐陪玩', 'casual': 30, 'tech': 50, 'god': 80, 'pro': 120, 'type': 'normal', 'billing': 'hour'},
                        {'name': '排位上分', 'casual': 40, 'tech': 70, 'god': 110, 'pro': 160, 'type': 'normal', 'billing': 'hour'},
                        {'name': '代练段位', 'casual': 60, 'tech': 100, 'god': 150, 'pro': 200, 'type': 'training', 'billing': 'round'},
                    ]
                },
                {
                    'name': '英雄联盟', 'sort_order': 3,
                    'items': [
                        {'name': '娱乐陪玩', 'casual': 25, 'tech': 45, 'god': 70, 'pro': 100, 'type': 'normal', 'billing': 'hour'},
                        {'name': '排位双排', 'casual': 35, 'tech': 55, 'god': 90, 'pro': 130, 'type': 'normal', 'billing': 'hour'},
                        {'name': '代练段位', 'casual': 50, 'tech': 80, 'god': 130, 'pro': 180, 'type': 'training', 'billing': 'round'},
                        {'name': '教学指导', 'casual': 40, 'tech': 70, 'god': 120, 'pro': 200, 'type': 'normal', 'billing': 'hour'},
                    ]
                },
                {
                    'name': 'CS2', 'sort_order': 4,
                    'items': [
                        {'name': '娱乐陪玩', 'casual': 30, 'tech': 50, 'god': 80, 'pro': 120, 'type': 'normal', 'billing': 'hour'},
                        {'name': '排位上分', 'casual': 40, 'tech': 65, 'god': 100, 'pro': 150, 'type': 'normal', 'billing': 'hour'},
                        {'name': '护航代打', 'casual': 55, 'tech': 85, 'god': 130, 'pro': 190, 'type': 'escort', 'billing': 'hour'},
                    ]
                },
                {
                    'name': 'PUBG', 'sort_order': 5,
                    'items': [
                        {'name': '娱乐陪玩', 'casual': 25, 'tech': 45, 'god': 70, 'pro': 110, 'type': 'normal', 'billing': 'hour'},
                        {'name': '吃鸡上分', 'casual': 35, 'tech': 55, 'god': 90, 'pro': 140, 'type': 'normal', 'billing': 'hour'},
                        {'name': '护航吃鸡', 'casual': 50, 'tech': 80, 'god': 120, 'pro': 170, 'type': 'escort', 'billing': 'hour'},
                    ]
                },
                {
                    'name': '永劫无间', 'sort_order': 6,
                    'items': [
                        {'name': '娱乐陪玩', 'casual': 30, 'tech': 50, 'god': 80, 'pro': 120, 'type': 'normal', 'billing': 'hour'},
                        {'name': '排位上分', 'casual': 40, 'tech': 60, 'god': 100, 'pro': 150, 'type': 'normal', 'billing': 'hour'},
                        {'name': '代练段位', 'casual': 55, 'tech': 90, 'god': 140, 'pro': 200, 'type': 'training', 'billing': 'round'},
                    ]
                },
            ]

            all_items = []
            for pd in projects_data:
                proj = Project(name=pd['name'], sort_order=pd['sort_order'])
                db.session.add(proj)
                db.session.flush()

                for idx, item_data in enumerate(pd['items']):
                    pi = ProjectItem(
                        project_id=proj.id,
                        name=item_data['name'],
                        price_casual=item_data['casual'],
                        price_tech=item_data['tech'],
                        price_god=item_data['god'],
                        price_pro=item_data.get('peak', item_data.get('pro', 0)),
                        price_devil=item_data.get('devil', item_data.get('peak', item_data.get('pro', 0))),
                        commission_rate=Decimal('80'),
                        billing_type=item_data['billing'],
                        project_type=item_data['type'],
                        sort_order=idx,
                    )
                    db.session.add(pi)
                    all_items.append(pi)

            db.session.commit()
            print(f"Created {len(projects_data)} game projects with items.")
        else:
            all_items = ProjectItem.query.all()

        # ======== 生成订单 ========
        if players and gods and all_items:
            # 清理旧订单
            Order.query.delete()
            CommissionLog.query.delete()
            db.session.commit()
            print("Cleared old orders.")

            staffs = [s for s in [staff1, staff2] if s]
            tiers = ['casual', 'tech', 'god', 'peak', 'devil']
            statuses_weights = [
                ('pending_report', 3),
                ('pending_confirm', 3),
                ('paid', 4),
                ('refunded', 1),
            ]

            print("Creating orders...")
            for i in range(60):
                created_at = datetime.now() - timedelta(
                    days=random.randint(0, 7),
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59)
                )

                status = random.choices(
                    [s[0] for s in statuses_weights],
                    weights=[s[1] for s in statuses_weights]
                )[0]

                god = random.choice(gods)
                player = random.choice(players)
                staff = random.choice(staffs) if staffs else None
                item = random.choice(all_items)
                tier = random.choice(tiers)

                base_price = item.get_price_by_tier(tier)
                extra_price = Decimal(str(random.choice([0, 0, 0, 10, 20])))
                addon_price = Decimal(str(random.choice([0, 0, 0, 15, 30, 50])))
                addon_desc = random.choice([None, None, '语音开黑', '教学指导', '指定英雄'])

                duration = Decimal(str(random.choice([1, 1.5, 2, 2.5, 3, 4])))
                unit_price = base_price + extra_price
                subtotal = unit_price * duration + addon_price
                discount = god.vip_discount / Decimal('100')
                total_price = (subtotal * discount).quantize(Decimal('0.01'))
                commission_rate = item.commission_rate
                player_earning = (total_price * commission_rate / Decimal('100')).quantize(Decimal('0.01'))
                shop_earning = total_price - player_earning

                order_type = item.project_type

                order = Order(
                    order_no=generate_order_no() + str(i).zfill(2),
                    boss_id=god.id,
                    player_id=player.id,
                    staff_id=staff.id if staff else None,
                    project_item_id=item.id,
                    price_tier=tier,
                    base_price=base_price,
                    extra_price=extra_price,
                    addon_desc=addon_desc,
                    addon_price=addon_price,
                    boss_discount=god.vip_discount,
                    total_price=total_price if status != 'pending_report' else Decimal('0'),
                    commission_rate=commission_rate,
                    player_earning=player_earning if status != 'pending_report' else Decimal('0'),
                    shop_earning=shop_earning if status != 'pending_report' else Decimal('0'),
                    order_type=order_type,
                    duration=duration if status != 'pending_report' else Decimal('0'),
                    status=status,
                    created_at=created_at,
                    remark=random.choice([None, None, '老板很好说话', '需要耐心', '']),
                )

                if status in ('pending_confirm', 'paid', 'refunded'):
                    order.total_price = total_price
                    order.player_earning = player_earning
                    order.shop_earning = shop_earning
                    order.duration = duration
                    order.fill_time = created_at
                    order.report_time = created_at + timedelta(hours=random.randint(1, 4))

                if status in ('paid', 'refunded'):
                    order.confirm_time = created_at + timedelta(hours=random.randint(4, 24))
                    order.pay_time = order.confirm_time

                if status == 'refunded':
                    order.refund_time = created_at + timedelta(days=1)

                db.session.add(order)

            db.session.commit()
            print("Created 60 orders.")

        # ======== VIP 等级配置 ========
        if VipLevel.query.count() == 0:
            print("Creating VIP levels...")
            vip_levels = [
                {'name': 'GOD', 'min_experience': 0, 'discount': 100, 'sort_order': 0,
                 'benefits': json.dumps(['基础身份铭牌'], ensure_ascii=False)},
                {'name': 'VIP1', 'min_experience': 1000, 'discount': 98, 'sort_order': 1,
                 'benefits': json.dumps(['98折优惠', 'VIP1铭牌'], ensure_ascii=False)},
                {'name': 'VIP2', 'min_experience': 5000, 'discount': 95, 'sort_order': 2,
                 'benefits': json.dumps(['95折优惠', 'VIP2铭牌', '专属播报'], ensure_ascii=False)},
                {'name': 'VIP3', 'min_experience': 15000, 'discount': 92, 'sort_order': 3,
                 'benefits': json.dumps(['92折优惠', 'VIP3铭牌', '专属播报', '优先派单'], ensure_ascii=False)},
                {'name': 'VIP4', 'min_experience': 50000, 'discount': 90, 'sort_order': 4,
                 'benefits': json.dumps(['9折优惠', 'VIP4铭牌', '专属播报', '优先派单', '生日福利'], ensure_ascii=False)},
                {'name': '总裁sama', 'min_experience': 100000, 'discount': 88, 'sort_order': 5,
                 'benefits': json.dumps(['88折优惠', '总裁铭牌', '专属频道', '优先派单', '生日福利', '专属客服'], ensure_ascii=False)},
            ]
            for vl_data in vip_levels:
                vl = VipLevel(**vl_data)
                db.session.add(vl)
            db.session.commit()
            print(f"Created {len(vip_levels)} VIP levels.")

        # ======== 礼物配置 ========
        if Gift.query.count() == 0:
            print("Creating gifts...")
            gifts_data = [
                {'name': '小星星', 'price': 10, 'gift_type': 'standard'},
                {'name': '爱心', 'price': 50, 'gift_type': 'standard'},
                {'name': '火箭', 'price': 100, 'gift_type': 'standard'},
                {'name': '皇冠', 'price': 500, 'gift_type': 'crown'},
                {'name': '城堡', 'price': 1000, 'gift_type': 'crown'},
                {'name': '跑车', 'price': 2000, 'gift_type': 'crown'},
                {'name': '游艇', 'price': 5000, 'gift_type': 'crown'},
                {'name': '星球', 'price': 10000, 'gift_type': 'crown'},
            ]
            for gd in gifts_data:
                gift = Gift(
                    name=gd['name'],
                    price=Decimal(str(gd['price'])),
                    gift_type=gd['gift_type'],
                    status=True,
                    # 留空表示走“播报管理-礼物播报”模板；仅在礼物管理里单独配置时才覆盖
                    broadcast_template=''
                )
                db.session.add(gift)
            db.session.commit()
            all_gifts = Gift.query.all()
            print(f"Created {len(gifts_data)} gifts.")

            # ======== 生成礼物订单 ========
            if players and gods and all_gifts:
                print("Creating gift orders...")
                staffs_list = [s for s in [staff1, staff2] if s]
                for i in range(20):
                    god = random.choice(gods)
                    player = random.choice(players)
                    staff = random.choice(staffs_list) if staffs_list else None
                    gift = random.choice(all_gifts)
                    qty = random.randint(1, 5)
                    total = gift.price * qty
                    p_earning = (total * Decimal('0.8')).quantize(Decimal('0.01'))
                    s_earning = total - p_earning
                    created_at = datetime.now() - timedelta(
                        days=random.randint(0, 7),
                        hours=random.randint(0, 23)
                    )
                    go = GiftOrder(
                        boss_id=god.id, player_id=player.id,
                        staff_id=staff.id if staff else None,
                        gift_id=gift.id,
                        quantity=qty, unit_price=gift.price,
                        total_price=total, commission_rate=Decimal('80'),
                        player_earning=p_earning, shop_earning=s_earning,
                        status='paid',
                        freeze_status='frozen' if gift.gift_type == 'crown' else 'normal',
                        created_at=created_at,
                    )
                    db.session.add(go)
                db.session.commit()
                print("Created 20 gift orders.")

        # ======== 播报配置 ========
        if BroadcastConfig.query.count() == 0:
            print("Creating broadcast configs...")
            thresholds = [500, 1000, 3000, 5000, 20000, 100000]
            for t in thresholds:
                bc = BroadcastConfig(
                    broadcast_type='recharge',
                    threshold=Decimal(str(t)),
                    template=f'{{user}} 充值了 {t} M币！感谢大佬的支持！',
                    status=True,
                )
                db.session.add(bc)
            db.session.commit()
            print(f"Created {len(thresholds)} broadcast configs.")

        print("Data initialization completed.")


if __name__ == '__main__':
    init_data()
