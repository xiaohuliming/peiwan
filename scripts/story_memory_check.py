#!/usr/bin/env python3
"""检查 KOOK 剧情 Mem0 长期记忆配置。

默认只做配置与连通性检查；加 `--smoke` 会写入一条测试记忆再检索。
"""
import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.services.story_memory_service import (
    memory_health_status,
    remember_story_turn,
    reset_memory_client,
    search_story_memories,
)


def main():
    parser = argparse.ArgumentParser(description='Check story Mem0 memory setup')
    parser.add_argument('--no-connection', action='store_true', help='skip Qdrant/Mem0 REST connectivity checks')
    parser.add_argument('--smoke', action='store_true', help='write and search a smoke-test memory')
    parser.add_argument('--strict', action='store_true', help='return non-zero when memory is disabled or not ready')
    parser.add_argument('--user-id', default='__story_mem0_smoke__', help='test KOOK user id for --smoke')
    args = parser.parse_args()

    app = create_app(start_background_tasks=False)
    with app.app_context():
        health = memory_health_status(check_connection=not args.no_connection)
        print(f"enabled: {health['enabled']}")
        print(f"backend: {health['backend']}")
        print(f"ready: {health['ready']}")
        for detail in health['details']:
            print(f"detail: {detail}")
        for issue in health['issues']:
            print(f"issue: {issue}")

        if not args.smoke:
            return 0 if (health['configured'] or not args.strict) else 2

        if not health['ready']:
            print('smoke: skipped because memory is not ready')
            return 2

        ok = remember_story_turn(
            args.user_id,
            user_input='Mem0 连通性测试：玩家告诉捷风自己会记住训练室的红色警报。',
            visible_text='捷风记下了这句话，并提醒玩家下次不要独自行动。',
            metadata={'source': 'story_memory_check', 'scene': 'smoke_test'},
        )
        print(f"smoke_add: {ok}")
        results = search_story_memories(args.user_id, '捷风 训练室 红色警报', limit=3)
        print(f"smoke_search_count: {len(results)}")
        for index, item in enumerate(results, start=1):
            print(f"memory_{index}: {item}")
        reset_memory_client()
        return 0 if ok and results else 3


if __name__ == '__main__':
    raise SystemExit(main())
