"""
冻结缓存批量对账脚本

用途:
1. 审计 users.m_bean_frozen 与实时冻结金额的差异
2. 可选地将 m_bean_frozen 回填为实时冻结总额

实时冻结总额来源:
- 提现待审核: WithdrawRequest.status == 'pending'
- 订单冻结: Order.status == 'paid' and freeze_status == 'frozen'
- 礼物冻结: GiftOrder.status == 'paid' and freeze_status == 'frozen'

用法:
    # 仅预览所有存在差异的用户
    python reconcile_frozen_balance_cache.py

    # 仅预览指定用户
    python reconcile_frozen_balance_cache.py --user-id 38

    # 真正回填数据库
    python reconcile_frozen_balance_cache.py --apply
"""
import argparse

from app import create_app
from app.extensions import db
from app.services.frozen_balance_service import (
    build_frozen_reconciliation_rows,
    quantize_money,
    reconcile_frozen_balance_cache,
)
from app.services.log_service import log_operation


def _fmt_money(value):
    return f'{quantize_money(value):.2f}'


def run_reconcile(apply=False, user_id=None, show_all=False, limit=None):
    app = create_app(start_background_tasks=False)

    with app.app_context():
        rows = build_frozen_reconciliation_rows(
            user_id=user_id,
            only_diff=not show_all,
            limit=limit,
        )

        if not rows:
            if user_id:
                print(f'用户 {user_id} 当前无冻结缓存差异。')
            else:
                print('未发现冻结缓存差异，无需处理。')
            return

        print(f'执行模式: {"APPLY(写入)" if apply else "PREVIEW(预览)"}')
        print(f'展示范围: {"全部命中用户" if show_all else "仅差异用户"}')
        if user_id:
            print(f'指定用户: {user_id}')
        if limit:
            print(f'数量限制: {limit}')
        print(f'命中记录数: {len(rows)}')
        print('-' * 132)
        print(
            f'{"用户ID":<8} {"展示名":<18} {"角色":<10} {"编号":<10} '
            f'{"缓存冻结":>12} {"实时冻结":>12} {"历史差异":>12} '
            f'{"提现":>10} {"订单":>10} {"礼物":>10}'
        )
        print('-' * 132)

        total_legacy = 0
        total_realtime = 0
        total_diff = 0
        changed_count = 0

        for row in rows:
            total_legacy += row['legacy_cache']
            total_realtime += row['realtime_total']
            total_diff += row['legacy_diff']
            if row['changed']:
                changed_count += 1

            print(
                f'{row["user_id"]:<8} {row["display_name"][:18]:<18} {row["role"]:<10} {row["user_code"][:10]:<10} '
                f'{_fmt_money(row["legacy_cache"]):>12} {_fmt_money(row["realtime_total"]):>12} {_fmt_money(row["legacy_diff"]):>12} '
                f'{_fmt_money(row["pending_withdraw"]):>10} {_fmt_money(row["order"]):>10} {_fmt_money(row["gift"]):>10}'
            )

        print('-' * 132)
        print(f'缓存冻结合计: {_fmt_money(total_legacy)}')
        print(f'实时冻结合计: {_fmt_money(total_realtime)}')
        print(f'历史差异合计: {_fmt_money(total_diff)}')
        print(f'存在差异用户数: {changed_count}')

        if not apply:
            print('预览完成，未写入数据库。')
            return

        updated_rows = reconcile_frozen_balance_cache(
            rows,
            log_fn=log_operation,
        )

        if not updated_rows:
            print('没有需要写入的差异，跳过提交。')
            return

        try:
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            print(f'写入失败，已回滚: {exc}')
            raise

        print(f'写入完成：已回填 {len(updated_rows)} 个用户的 m_bean_frozen 缓存。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='批量对账并回填冻结缓存 m_bean_frozen。')
    parser.add_argument('--apply', action='store_true', help='执行写入（默认仅预览）')
    parser.add_argument('--user-id', type=int, default=0, help='仅查看/修复指定用户')
    parser.add_argument('--all', action='store_true', help='预览时包含无差异用户')
    parser.add_argument('--limit', type=int, default=0, help='限制扫描用户数量（按用户 ID 正序）')
    args = parser.parse_args()

    run_reconcile(
        apply=args.apply,
        user_id=(args.user_id or None),
        show_all=args.all,
        limit=(args.limit or None),
    )
