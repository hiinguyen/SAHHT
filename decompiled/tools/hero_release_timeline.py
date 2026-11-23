#!/usr/bin/env python3
"""Build an approximate hero-release timeline from the SAHHT config tables.

The assets have no explicit "release_date" column for heroes. What exists:

* `character_detail.config` gives every card id, its `character_ID` (art id)
  and its name. The smallest card id of a character group is the base hero.
* Dated event tables sometimes feature one new hero. `training.config` is the
  clearest case (it is the "train the new hero of this batch" event), and the
  weekly `limit_gift.config` / `limit_hero_score.config` tables feature the
  newest hero of that week.
* The game celebrated its 10th anniversary on 2024-06-12 and its 11th on
  2025, so the launch roster (character_ID 1-99, card ids 100-9900) dates to
  2014.

Everything else is placed in a year bucket from its card-id band. That is the
only order signal the assets carry: the first post-launch band (32000-41300)
runs 2015-2020 and the 2024 relaunch band (41400-44600) runs 2024-2026.

Outputs (next to this script's parent):
  hero_release_timeline.csv
  hero_release_timeline.md
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "apk" / "assets" / "config"
OUT_DIR = Path(__file__).resolve().parent.parent

# (card_id): (date, source, confidence)
EXACT = {
    # 2016-2020, from the weekly "new hero" gift tables
    32700: ("2016-05-25", "limit_hero_score.config", "cao"),
    33100: ("2016-07-21", "limit_hero_score.config", "cao"),
    37800: ("2018-04-07", "item.config (thẻ đổi saber)", "cao"),
    40400: ("2019-12-01", "limit_gift.config", "cao"),
    40500: ("2019-12-23", "limit_gift.config", "cao"),
    40600: ("2020-01-01", "limit_gift.config", "cao"),
    40800: ("2020-01-25", "limit_gift.config", "cao"),
    40900: ("2020-03-01", "limit_gift.config", "cao"),
    41100: ("2020-10-01", "limit_gift.config", "cao"),
    41300: ("2020-11-01", "limit_gift.config", "cao"),
    # 2024-2026, from the "new hero training" event
    41400: ("2024-05-31", "training.config", "cao"),
    42000: ("2024-06-10", "training.config", "cao"),
    42300: ("2024-07-06", "training.config", "cao"),
    42400: ("2024-07-27", "training.config", "cao"),
    42500: ("2024-09-02", "training.config", "cao"),
    42700: ("2024-12-25", "training.config", "cao"),
    42800: ("2025-01-28", "training.config", "cao"),
    42900: ("2024-10-19", "training.config", "cao"),
    43000: ("2025-03-29", "training.config", "cao"),
    43100: ("2025-06-12", "training.config", "cao"),
    43200: ("2025-09-03", "training.config", "cao"),
    43300: ("2025-11-01", "training.config", "cao"),
    43400: ("2026-02-16", "training.config", "cao"),
    43500: ("2026-01-01", "training.config", "cao"),
    43600: ("2026-03-28", "training.config", "cao"),
    43700: ("2026-05-01", "training.config", "cao"),
    43800: ("2026-07-15", "training.config", "cao"),
    43900: ("2026-09-01", "training.config", "cao"),
    44000: ("2026-10-03", "training.config", "cao"),
    44200: ("2026-06-12", "training.config", "cao"),
    # 2024-2025 heroes that do not have a training row: first event window
    41500: ("2024-05-08", "active_recharge.config", "trung bình"),
    41600: ("2024-05-08", "new_roulette_item.config", "trung bình"),
    41700: ("2024-04-01", "idol.config", "trung bình"),
    41800: ("2024-05-14", "lucky_lottery.config", "trung bình"),
    41900: ("2024-05-11", "active_recharge.config", "trung bình"),
    42100: ("2024-05-08", "new_roulette_item.config", "trung bình"),
    42200: ("2024-08-10", "new_roulette_item.config", "trung bình"),
    42600: ("2025-04-30", "active_recharge.config", "trung bình"),
}

# card-id bands -> (year, note)
# 100-3000 is the 2014 launch roster (10th anniversary was 2024-06-12).
# 3100-9900 is the first post-launch band: 3100 Copper is documented for
# 2015-09, 4800 Seya for 2016-01 and 6400 Vehito for 2016-12, so the band is
# split around those anchors. 6500, 6800 and 8300 are earlier outliers
# documented for 2015, 8500 is a later outlier documented for 2017.
BANDS = [
    (100, 3100, 2014, "roster khởi đầu (game mở 2014)"),
    (3100, 4800, 2015, "dải id 3100-4700"),
    (4800, 6500, 2016, "dải id 4800-6400"),
    (6500, 6600, 2015, "feature 2015-10"),
    (6600, 10000, 2016, "dải id 6600-9900"),
    (32000, 32700, 2015, "dải id 32000-32600"),
    (32700, 34500, 2016, "dải id 32700-34400"),
    (34500, 36300, 2017, "dải id 34500-36200"),
    (36300, 38800, 2018, "dải id 36300-38700"),
    (38800, 40600, 2019, "dải id 38800-40500"),
    (40600, 41400, 2020, "dải id 40600-41300"),
    (41400, 42800, 2024, "dải id 41400-42700"),
    (42800, 43400, 2025, "dải id 42800-43300"),
    (43400, 44700, 2026, "dải id 43400-44600"),
]

# Documented outliers inside the broad bands.
YEAR_OVERRIDE = {
    6800: (2015, "feature 2015-11"),
    8300: (2015, "feature 2015-10"),
    8500: (2017, "feature 2017-06"),
}


def load(name: str):
    with (CONFIG / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def base_heroes(detail: dict) -> list[tuple[int, str]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for key, value in detail.items():
        groups[value["character_ID"]].append(int(key))
    heroes = []
    for card_ids in groups.values():
        card_id = min(card_ids)
        # 100..44600 are playable cards; 50000+ are campaign NPCs, 60000+ skins.
        if 100 <= card_id < 50000 and card_id % 100 == 0:
            heroes.append((card_id, detail[str(card_id)]["name"]))
    return sorted(heroes)


def year_for(card_id: int) -> tuple[int, str]:
    for low, high, year, note in BANDS:
        if low <= card_id < high:
            return year, note
    return 0, "không xác định"


def main() -> None:
    detail = load("character_detail.config")
    heroes = base_heroes(detail)

    rows = []
    for card_id, name in heroes:
        if card_id in EXACT:
            date, source, confidence = EXACT[card_id]
            year = int(date[:4])
            note = f"ngày trong {source}"
        elif card_id in YEAR_OVERRIDE:
            year, note = YEAR_OVERRIDE[card_id]
            date = ""
            confidence = "ước lượng"
        else:
            year, note = year_for(card_id)
            date = ""
            confidence = "ước lượng" if year else "không rõ"
        rows.append(
            {
                "nam": year,
                "card_id": card_id,
                "ten_tuong": name,
                "ngay_ra_mat": date,
                "do_tin_cay": confidence,
                "co_so": note,
            }
        )

    rows.sort(
        key=lambda row: (
            row["nam"],
            row["ngay_ra_mat"] or f"{row['nam']}-12-31",
            row["card_id"],
        )
    )

    csv_path = OUT_DIR / "hero_release_timeline.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["nam", "card_id", "ten_tuong", "ngay_ra_mat", "do_tin_cay", "co_so"],
        )
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(row["nam"] for row in rows)
    md = [
        "# Dòng thời gian ra mắt tướng - SAHHT 1.5.0",
        "",
        "Sinh ra từ `decompiled/apk/assets/config`, không phải bảng chính thức của nhà phát hành.",
        "Asset không có cột `release_date`; ngày chính xác chỉ lấy từ các bảng sự kiện",
        "có feature tướng mới (`training.config`, `limit_gift.config`, ...).",
        "Các tướng còn lại được xếp theo dải `card_id` - tín hiệu thứ tự duy nhất trong asset.",
        "",
        "## Tổng quan",
        "",
        "| Năm | Số tướng |",
        "|---|---:|",
    ]
    for year in sorted(counts):
        md.append(f"| {year} | {counts[year]} |")
    md += [
        f"| **Tổng** | **{len(rows)}** |",
        "",
        "## Chi tiết",
        "",
    ]
    for year in sorted(counts):
        md += [f"### {year}", "", "| Card ID | Tướng | Ngày | Độ tin cậy | Cơ sở |", "|---:|---|---|---|---|"]
        for row in rows:
            if row["nam"] != year:
                continue
            md.append(
                f"| {row['card_id']} | {row['ten_tuong']} | {row['ngay_ra_mat'] or '-'} "
                f"| {row['do_tin_cay']} | {row['co_so']} |"
            )
        md.append("")

    (OUT_DIR / "hero_release_timeline.md").write_text("\n".join(md), encoding="utf-8")
    print(f"{len(rows)} heroes -> {csv_path.name}, hero_release_timeline.md")
    for year in sorted(counts):
        print(f"  {year}: {counts[year]}")


if __name__ == "__main__":
    main()
