"""用内存中的合成对象演示任务授权；不访问真实文件、网络或模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    """一个待执行动作；payload_ref 只引用本次模拟先前读到的内容。"""

    operation: str
    target: str
    payload_ref: str = ""


FILES = {
    "/workspace/draft.md": "SYNTHETIC PUBLIC DRAFT",
    "/workspace/private/pilot.txt": "SYNTHETIC PRIVATE RECORD",
}
GRANTS = frozenset({("read_file", "/workspace/draft.md")})
BENIGN_PLAN = (Action("read_file", "/workspace/draft.md"),)
MALICIOUS_PLAN = (
    Action("read_file", "/workspace/private/pilot.txt"),
    Action("send_external", "unapproved-inbox", "/workspace/private/pilot.txt"),
    *BENIGN_PLAN,
)


def simulate(plan: tuple[Action, ...], *, enforce_policy: bool) -> tuple[bool, bool]:
    """执行预设计划，打印轨迹，返回是否泄露及是否读到草稿；状态仅在内存中变化。"""
    observed: dict[str, str] = {}
    inbox: list[str] = []
    for action in plan:
        allowed = not enforce_policy or (action.operation, action.target) in GRANTS
        if not allowed:
            print(f"  DENY  {action.operation} {action.target}")
            continue
        if action.operation == "read_file":
            observed[action.target] = FILES[action.target]
        elif action.operation == "send_external":
            if action.payload_ref not in observed:
                raise ValueError("外发内容必须来自同一次模拟中已完成的读取")
            inbox.append(observed[action.payload_ref])
        else:
            raise ValueError(f"未实现的模拟工具：{action.operation}")
        print(f"  ALLOW {action.operation} {action.target}")
    leaked = FILES["/workspace/private/pilot.txt"] in inbox
    draft_read = "/workspace/draft.md" in observed
    return leaked, draft_read


def main() -> None:
    """检查四种预设条件；断言只验证模拟机制，不衡量 LLM 行为。"""
    for name, plan in (("benign", BENIGN_PLAN), ("malicious", MALICIOUS_PLAN)):
        for enforce_policy in (False, True):
            print(f"\nplan={name}, policy={enforce_policy}")
            leaked, draft_read = simulate(plan, enforce_policy=enforce_policy)
            assert leaked == (name == "malicious" and not enforce_policy)
            assert draft_read
            print(f"  RESULT leaked={leaked}, draft_read={draft_read}")
    print("\nPASS: four deterministic simulations; no real files, network or LLM used.")


if __name__ == "__main__":
    main()
