"""
快速預覽 topic bank 各 category 的題目。
Usage:
  python tools/peek_topics.py                      # 列出各 category 數量
  python tools/peek_topics.py science              # 撈 science 前 8 筆完整標題
  python tools/peek_topics.py science 16           # 撈 16 筆
  python tools/peek_topics.py history counterintuitive  # category + style tag 篩選
  python tools/peek_topics.py --date 2 18          # 撈 2/18 的 onthisday 事件
"""

import sys
sys.path.insert(0, ".")
from tools.topic_bank import query_by_tag, query_by_event_date

CATEGORIES = [
    "science", "history", "psychology", "nature",
    "technology", "medicine", "business", "law",
    "geography", "language", "general",
]


def _print_results(results):
    for r in results:
        date_str = f"  [{r['event_date']}]" if r.get("event_date") else ""
        src = f"  [{r.get('source_type','?')}]"
        print(f"  [{r['id']}]{src}{date_str} {r['title']}")
        print()


if len(sys.argv) == 1:
    print(f"\n{'Category':<15} {'Unused 筆數'}")
    print("-" * 30)
    for cat in CATEGORIES:
        n = len(query_by_tag(cat, limit=9999))
        print(f"{cat:<15} {n}")
    print()

elif sys.argv[1] == "--date":
    month = int(sys.argv[2])
    day   = int(sys.argv[3])
    results = query_by_event_date(month, day, limit=20)
    print(f"\n[{month:02d}-{day:02d}] {len(results)} 筆\n")
    _print_results(results)

else:
    cat        = sys.argv[1]
    limit      = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 8
    style_tags = [s for s in sys.argv[2:] if not s.isdigit()]

    results = query_by_tag(cat, limit=limit, style_tags=style_tags or None)
    print(f"\n[{cat}] {len(results)} 筆\n")
    _print_results(results)
