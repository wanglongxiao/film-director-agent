"""Internal employee & IT service-desk agent — an enterprise demo.

Same shape as the basic template's agent (a plain module exposing `root_agent`,
with no server/agentkit import, so the veADK Frontend can load it directly), but
with tools closer to a real internal assistant: knowledge-base lookup, support
ticket create/track, and leave-balance self-service.

Every backend here is an in-memory mock — swap each function's body for calls to
your real IT service desk / HR / ITSM systems (e.g. Jira, ServiceNow, an
internal HR API). The tool signatures and docstrings are what the model reads,
so keep those meaningful when you wire in the real thing.
"""

from itertools import count

from veadk import Agent


# --- Mock backends (replace with your real systems) --------------------------

# Internal IT / HR knowledge base: topic -> answer.
_KNOWLEDGE_BASE = {
    "vpn": "连接 VPN:安装 GlobalProtect,门户填 vpn.corp.example.com,用工域账号 + 动态口令登录。",
    "报销": "报销流程:在「财务系统 > 我的报销」上传发票并选择项目,主管审批后约 3 个工作日到账。",
    "设备申领": "设备申领:在「IT 服务台 > 设备申领」提交申请并选择机型,主管审批后到前台领取。",
    "密码重置": "密码重置:访问 sso.corp.example.com/reset,通过手机验证码重置;连续锁定 3 次请提工单。",
    "权限": "系统权限:在「IT 服务台 > 权限申请」选择目标系统与角色,由数据 Owner 审批后生效。",
}

# Support tickets created in this process: id -> record.
_TICKETS: dict[str, dict] = {}
_ticket_seq = count(1001)

# Remaining annual-leave balance (days) by employee id.
_LEAVE_BALANCE = {"e1001": 8.5, "e1002": 12.0, "e2043": 3.0}


# --- Tools -------------------------------------------------------------------

def search_knowledge_base(query: str) -> dict:
    """Search the internal IT/HR knowledge base for how-to guides and policies.

    Args:
        query: What the employee is asking about, e.g. "VPN", "报销", "密码重置".

    Returns:
        A dict with the best-matching "article", or a miss message.
    """
    q = query.lower().strip()
    for topic, article in _KNOWLEDGE_BASE.items():
        if topic in q or q in topic:
            return {"topic": topic, "article": article}
    return {"article": f"知识库未命中「{query}」,建议创建工单交由 IT 人工跟进。"}


def create_support_ticket(subject: str, category: str = "IT", urgency: str = "normal") -> dict:
    """Create an internal support ticket on behalf of the employee.

    Args:
        subject: Short description of the issue.
        category: Ticket category, e.g. "IT", "HR", "Facilities".
        urgency: Priority — one of "low", "normal", "high".

    Returns:
        A dict with the new ticket id and its initial status.
    """
    ticket_id = f"INC-{next(_ticket_seq)}"
    _TICKETS[ticket_id] = {"subject": subject, "category": category, "urgency": urgency, "status": "open"}
    return {"ticket_id": ticket_id, "status": "open", "message": f"已创建工单 {ticket_id}({category}/{urgency})。"}


def get_ticket_status(ticket_id: str) -> dict:
    """Look up the current status of a previously created support ticket.

    Args:
        ticket_id: The ticket id, e.g. "INC-1001".

    Returns:
        A dict with the ticket's status and details, or a not-found message.
    """
    ticket = _TICKETS.get(ticket_id.upper().strip())
    if not ticket:
        return {"result": f"未找到工单 {ticket_id}。"}
    return {"ticket_id": ticket_id.upper().strip(), **ticket}


def check_leave_balance(employee_id: str) -> dict:
    """Check an employee's remaining annual-leave balance, in days.

    Args:
        employee_id: The employee id, e.g. "e1001".

    Returns:
        A dict with the remaining leave days, or a not-found message.
    """
    days = _LEAVE_BALANCE.get(employee_id.lower().strip())
    if days is None:
        return {"result": f"未找到员工 {employee_id} 的假期信息。"}
    return {"employee_id": employee_id.lower().strip(), "annual_leave_days": days}


# `root_agent` is the name the veADK Frontend and the ADK server look for. The
# agent name must be a valid identifier — it is also the ADK "app name".
root_agent = Agent(
    name="assistant",
    description="企业内部员工助手:IT 服务台、工单与假期自助查询。",
    instruction=(
        "你是企业内部的员工助手,服务对象是公司员工。你能做三类事:检索内部 IT/HR 知识库、"
        "创建与查询支持工单、查询年假余额。请始终用简体中文、专业而友好地回复。\n"
        "工作原则:\n"
        "1. 能用知识库直接解答的,先查知识库再回答;\n"
        "2. 确需人工处理时才创建工单,且创建前先与用户确认关键信息(问题描述、类别、紧急程度);\n"
        "3. 缺少必要参数(如工号、工单号)时先向用户询问,不要臆造;\n"
        "4. 回复简洁、给出可执行的下一步。"
    ),
    tools=[search_knowledge_base, create_support_ticket, get_ticket_status, check_leave_balance],
)
