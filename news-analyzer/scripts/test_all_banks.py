"""全量验证所有 18 家银行配置。"""
import sys, os

# 设置 UTF-8 输出
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
elif hasattr(sys.stdout, 'buffer'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from website_scraper import BANK_CONFIGS, fetch_list_page

print(f"银行配置总数: {len(BANK_CONFIGS)}\n")

success = 0
failure = 0
for name, bank in BANK_CONFIGS.items():
    try:
        items = fetch_list_page(bank)
        print(f"[{'OK' if items else '--'}] {bank.short_name or name:<6} {bank.name:>8} → {len(items)} 条")
        if items:
            success += 1
        else:
            failure += 1
    except Exception as e:
        print(f"[!!] {bank.short_name or name:<6} {bank.name:>8} → 异常: {e}")
        failure += 1

print(f"\n成功: {success} | 失败: {failure} | 总计: {len(BANK_CONFIGS)}")
