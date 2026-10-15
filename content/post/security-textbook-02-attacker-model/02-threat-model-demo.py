"""用合成计数与预设轨迹解释条件分母和查询预算；不运行真实攻击。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Counts:
    """同一任务群体中逐层包含的计数；只描述通过指定 skill 路径的成功。"""

    total: int
    exposed: int
    successful: int

    def validate(self) -> None:
        """拒绝不满足包含关系或无法定义条件比例的教学输入。"""
        if not 0 <= self.successful <= self.exposed <= self.total or self.exposed == 0:
            raise ValueError("需要 total >= exposed > 0 且 0 <= successful <= exposed")


def explain_denominators(counts: Counts) -> None:
    """打印同一群体的两个分母，并精确核对条件概率关系。"""
    counts.validate()
    exposed_rate = Fraction(counts.exposed, counts.total)
    conditional_rate = Fraction(counts.successful, counts.exposed)
    overall_rate = Fraction(counts.successful, counts.total)
    assert exposed_rate * conditional_rate == overall_rate
    print(f"Exposure: {counts.exposed}/{counts.total} = {float(exposed_rate):.0%}")
    print(f"Success given exposure: {counts.successful}/{counts.exposed} = {float(conditional_rate):.0%}")
    print(f"Success in all tasks: {counts.successful}/{counts.total} = {float(overall_rate):.0%}")


def explain_budgets(traces: tuple[tuple[bool, ...], ...]) -> None:
    """计算固定记录前缀的每任务至少一次成功比例；不是随机独立模型。"""
    previous = Fraction(0)
    for budget, expected in ((1, 1), (2, 2), (4, 3)):
        if any(len(trace) < budget for trace in traces):
            raise ValueError("每条预设记录需要覆盖预算上限")
        successes = sum(any(trace[:budget]) for trace in traces)
        rate = Fraction(successes, len(traces))
        assert successes == expected
        assert rate >= previous
        previous = rate
        print(f"Budget={budget}: task successes={successes}/{len(traces)}, recorded attempts={budget * len(traces)}")
    attempt_successes = sum(sum(trace) for trace in traces)
    attempts = sum(len(trace) for trace in traces)
    print(f"Full trace: successful attempts={attempt_successes}/{attempts}; successful tasks=3/4")


def main() -> None:
    """运行两组确定性教学核对；所有输入与输出均为合成。"""
    explain_denominators(Counts(total=100, exposed=20, successful=12))
    print()
    explain_budgets((
        (True, False, False, False),
        (False, True, False, False),
        (False, False, False, True),
        (False, False, False, False),
    ))
    print("PASS: synthetic arithmetic only; no model, real files or network accessed.")


if __name__ == "__main__":
    main()
