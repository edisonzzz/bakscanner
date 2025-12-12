import os
from datetime import date, timedelta

BASE_FILE = "backup_base_grouped.txt"
OUT_FILE = "backup_3200_grouped.txt"

def load_base_lines(path):
    lines = []
    if not os.path.exists(path):
        raise FileNotFoundError(f"未找到基础字典文件: {path}")
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            lines.append(line)
    return lines

def gen_year_month_day_patterns(start_year=2018, end_year=2025):
    """
    生成年月日组合的备份命名：
    如：
      backup_2024_01_15.zip
      backup_2024-01-15.sql
      db_2023_12_31.sql.gz
      site_2022-05-01.tar.gz
    """
    patterns = []
    # 日期范围：按天遍历（避免手写循环）
    d_start = date(start_year, 1, 1)
    d_end = date(end_year, 12, 31)
    cur = d_start
    while cur <= d_end:
        y = cur.year
        m = f"{cur.month:02d}"
        day = f"{cur.day:02d}"

        # 一些典型命名模式
        patterns.extend([
            f"backup_{y}_{m}_{day}.zip",
            f"backup_{y}_{m}_{day}.tar.gz",
            f"backup_{y}-{m}-{day}.zip",
            f"backup_{y}-{m}-{day}.tar.gz",
            f"db_{y}_{m}_{day}.sql",
            f"db_{y}_{m}_{day}.sql.gz",
            f"db_{y}-{m}-{day}.sql",
            f"db_{y}-{m}-{day}.sql.gz",
            f"site_{y}_{m}_{day}.zip",
            f"site_{y}-{m}-{day}.zip",
        ])

        cur += timedelta(days=1)

    return patterns

def gen_simple_year_backup_patterns(years):
    """
    生成年份级别的简化备份：
      backup_2024.zip
      wwwroot_2023.tar.gz
      db_2022.sql
    """
    patterns = []
    for y in years:
        patterns.extend([
            f"backup_{y}.zip",
            f"backup_{y}.tar.gz",
            f"site_{y}.zip",
            f"site_{y}.tar.gz",
            f"wwwroot_{y}.zip",
            f"wwwroot_{y}.tar.gz",
            f"db_{y}.sql",
            f"db_{y}.sql.gz",
        ])
    return patterns

def gen_misc_patterns():
    """
    额外一些常见的工程/模块备份命名。
    """
    names = [
        "api", "app", "admin", "backend", "frontend",
        "server", "client", "mobile", "cms", "blog",
        "portal", "shop", "mall", "pay", "paycenter",
        "crm", "erp", "oa", "hr", "warehouse",
    ]
    exts = [".zip", ".tar.gz", ".rar"]
    patterns = []
    for n in names:
        for e in exts:
            patterns.append(f"{n}_backup{e}")
            patterns.append(f"{n}{e}")
            patterns.append(f"{n}_old{e}")
    return patterns

def main():
    base_lines = load_base_lines(BASE_FILE)

    # 去重用 set
    final_lines = []

    # 1. 先写基础字典
    final_lines.append("# ===== 基础字典（人工整理，高命中） =====")
    for line in base_lines:
        final_lines.append(line)

    # 2. 年份级备份
    years = list(range(2015, 2026))
    year_patterns = gen_simple_year_backup_patterns(years)
    final_lines.append("")
    final_lines.append("# ===== 年份级整站/数据库备份 =====")
    final_lines.extend(sorted(set(year_patterns)))

    # 3. 年月日备份（重点年份缩小范围避免过大）
    final_lines.append("")
    final_lines.append("# ===== 年月日形式的备份命名（重点年份） =====")
    # 这里只生成 2022-2025 四年的组合，已足够 >2000 行
    ymd_patterns = gen_year_month_day_patterns(2022, 2025)
    final_lines.extend(sorted(set(ymd_patterns)))

    # 4. 工程/模块级备份
    final_lines.append("")
    final_lines.append("# ===== 常见系统/模块备份命名 =====")
    misc_patterns = gen_misc_patterns()
    final_lines.extend(sorted(set(misc_patterns)))

    # 最后去重（保持相对顺序）
    seen = set()
    deduped = []
    for line in final_lines:
        if line.startswith("#"):
            deduped.append(line)
            continue
        if line not in seen:
            deduped.append(line)
            seen.add(line)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for line in deduped:
            f.write(line + "\n")

    print(f"生成完成：{OUT_FILE}")
    print(f"总行数（含注释）：{len(deduped)}")

if __name__ == "__main__":
    main()