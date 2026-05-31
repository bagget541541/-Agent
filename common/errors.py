"""
统一错误处理框架

设计原则：
1. **管道级容错**：单步失败不应阻断后续步骤
2. **可追踪**：每个错误携带 error_code + step + context
3. **兼容性**：不改变已有函数的签名/返回值类型，只在下层包装

使用方式：
    from common.errors import PipelineResult, safe_step

    result = PipelineResult()
    result.run_step("抓取银行公告", lambda: step2_fetch_bank_news(days), default=[])
    result.run_step("生成报告", lambda: step4_generate_report(batch), default=None)
    result.print_summary()
"""

import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


# ── 错误信息数据类 ────────────────────────────────────────

@dataclass
class StepError:
    """单步错误信息"""
    step: str
    message: str
    exception: Optional[Exception] = None
    traceback_str: str = ""

    def short_str(self) -> str:
        return f"[{self.step}] {self.message}"

    def detail_str(self) -> str:
        s = f"[{self.step}] {self.message}"
        if self.traceback_str:
            s += f"\n{self.traceback_str}"
        return s


# ── 管道级错误收集器 ──────────────────────────────────────

class PipelineResult:
    """管道执行结果收集器。

    记录每步的成败，提供最终聚合信息。不影响已有函数的返回值。
    """

    def __init__(self, pipeline_name: str = "Pipeline"):
        self.pipeline_name = pipeline_name
        self.errors: list[StepError] = []
        self.start_time = datetime.now()
        self._step_count = 0
        self._success_count = 0

    @property
    def success(self) -> bool:
        return len(self.errors) == 0

    @property
    def total_steps(self) -> int:
        return self._step_count

    def run_step(self, step_name: str, fn: Callable[[], Any], *, default: Any = None) -> Any:
        """执行一个步骤，捕获异常后用默认值降级。

        Args:
            step_name: 步骤名称（用于错误报告）
            fn: 无参数可调用对象
            default: 失败时的默认返回值

        Returns:
            fn 的返回值，或 default
        """
        self._step_count += 1
        try:
            value = fn()
            self._success_count += 1
            return value
        except Exception as e:
            tb = traceback.format_exc()
            err = StepError(
                step=step_name,
                message=str(e) or type(e).__name__,
                exception=e,
                traceback_str=tb,
            )
            self.errors.append(err)
            print(f"  [{step_name}] [FAIL] {e}", file=sys.stderr)
            return default

    def print_summary(self):
        """打印管道执行摘要"""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        total = self._step_count
        ok = self._success_count
        fail = total - ok

        print("\n" + "=" * 60)
        print(f"  {self.pipeline_name} — 摘要")
        print(f"  时间: {elapsed:.1f}s | 步骤: {ok}/{total} 成功")
        if fail:
            print(f"  失败: {fail} 步")
            for err in self.errors:
                print(f"    [FAIL] {err.short_str()}")
            print(f"  （管道继续运行，失败步骤已使用默认值降级）")
        else:
            print(f"  全部成功 [v]")
        print("=" * 60)

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def get_error_report(self) -> dict:
        return {
            "pipeline": self.pipeline_name,
            "success": self.success,
            "total_steps": self._step_count,
            "success_count": self._success_count,
            "fail_count": self._step_count - self._success_count,
            "errors": [{"step": e.step, "message": e.message} for e in self.errors],
        }


# ── 便捷别名（兼容旧版命名） ──────────────────────────────

safe_step = PipelineResult.run_step


# ── 简单日志工具（统一输出格式） ──────────────────────────

def log_info(step: str, message: str):
    """统一信息日志"""
    print(f"  [{step}] {message}")


def log_warn(step: str, message: str):
    """统一警告日志"""
    print(f"  [{step}] [WARN] {message}", file=sys.stderr)


def log_error(step: str, message: str):
    """统一错误日志"""
    print(f"  [{step}] [ERR] {message}", file=sys.stderr)
