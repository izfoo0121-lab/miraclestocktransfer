"""
Miracle Transfer Bot — 简体中文版
Flow:
1. 发送方在群里贴转货模板
2. 机器人添加"确认收货"按钮（只有收货方可以点）
3. 收货方确认后，出现审批按钮
4. 主管审批
5. 账务更新AutoCount
"""

import os, json, logging, sys, re
from datetime import datetime

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────
BOT_TOKEN          = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GROUP_ID           = int(os.environ.get("GROUP_ID", "0"))
HISTORY_FILE       = "history.json"
MEMBERS_FILE       = "members.json"
APPROVER_USERNAMES = set(os.environ.get("APPROVERS", "").lower().split(","))
ACCOUNTS_CHAT_ID   = int(os.environ.get("ACCOUNTS_CHAT_ID", "0"))
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "")  # e.g. izfoo0121-lab/miraclestocktransfer
GITHUB_BRANCH      = os.environ.get("GITHUB_BRANCH", "main")

# Pre-loaded agents: display name (lowercase) → @username (lowercase, no @)
PRESET_AGENTS = {
    "ben":   "benben9488",
    "ki-mi": "ahki4418",
    "yi":    "psyducknew",
    "isaac": "gt138888",
    # 以下成员需要 /register 注册
    # kent, cj, jacky, james, jw, kean, kee, kf, kw, leon, nmk, sam
}


# ── Members DB ─────────────────────────────────────────────────────────────────
def load_members() -> dict:
    """Returns {name_lower: {user_id, username, display_name}}"""
    base = {}
    for name, uname in PRESET_AGENTS.items():
        base[name] = {"user_id": None, "username": uname, "display_name": name.upper()}
    if os.path.exists(MEMBERS_FILE):
        with open(MEMBERS_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        base.update(saved)
    return base

def save_members(members: dict):
    with open(MEMBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(members, f, ensure_ascii=False, indent=2)

def find_member_by_user(user) -> str | None:
    """Returns the registered name for a Telegram user, or None."""
    members = load_members()
    uid  = user.id
    uname = (user.username or "").lower()
    for name, info in members.items():
        if info.get("user_id") == uid:
            return name
        if uname and info.get("username","").lower() == uname:
            return name
    return None

def is_receiver(user, to_field: str) -> bool:
    """Check if this user matches the To: field."""
    to_clean = to_field.strip().lower().lstrip("@")
    # Direct username match
    uname = (user.username or "").lower()
    if uname and uname == to_clean:
        return True
    # Check by registered name
    reg_name = find_member_by_user(user)
    if reg_name and reg_name.lower() == to_clean:
        return True
    if reg_name and (reg_name.lower() in to_clean or to_clean in reg_name.lower()):
        return True
    # Check members dict
    members = load_members()
    if to_clean in members:
        info = members[to_clean]
        if info.get("user_id") == user.id:
            return True
        if uname and info.get("username","").lower() == uname:
            return True
    return False


# ── History ────────────────────────────────────────────────────────────────────
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_history(records):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


# ── Push to GitHub ────────────────────────────────────────────────────────────
async def push_to_github(content: str, filepath: str, message: str):
    """Push a file to GitHub via API."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    import base64, httpx
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    # Get current SHA if file exists
    sha = None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                sha = r.json().get("sha")
    except Exception:
        pass
    # Push file
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    try:
        async with httpx.AsyncClient() as client:
            r = await client.put(url, headers=headers, json=payload)
            if r.status_code in (200, 201):
                logger.info(f"推送到 GitHub 成功: {filepath}")
            else:
                logger.warning(f"GitHub 推送失败: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logger.warning(f"GitHub 推送错误: {e}")


# ── Permission ─────────────────────────────────────────────────────────────────
def is_approver(user) -> bool:
    if not APPROVER_USERNAMES or APPROVER_USERNAMES == {""}:
        return True
    return (user.username or "").lower() in APPROVER_USERNAMES


# ── Parse template ─────────────────────────────────────────────────────────────
def parse_transfer(text: str) -> dict | None:
    lines = [l.strip() for l in text.splitlines()]
    has_from = any("from" in l.lower() and ":" in l for l in lines)
    has_to   = any(l.lower().startswith("to") and ":" in l for l in lines)
    if not has_from or not has_to:
        return None

    data = {"from": "", "to": "", "date": "", "items": [], "reasons": [], "account": "", "cc": ""}
    in_items = False

    for line in lines:
        ll = line.lower()
        if ll.startswith("from") and ":" in line:
            data["from"] = line.split(":", 1)[1].strip()
        elif ll.startswith("to") and ":" in line:
            data["to"] = line.split(":", 1)[1].strip()
        elif ll.startswith("date") and ":" in line:
            data["date"] = line.split(":", 1)[1].strip()
        elif ll.startswith("account") and ":" in line:
            data["account"] = line.split(":", 1)[1].strip()
        elif (ll.startswith("cc") or ll.startswith("cc")) and ":" in line:
            data["cc"] = line.split(":", 1)[1].strip()
        elif line and line[0].isdigit() and "." in line[:3]:
            if "✅" in line or "✓" in line:
                reason = line.split(".", 1)[1].strip().replace("✅","").replace("✓","").strip()
                reason = re.sub(r'[（(].+?[）)]', '', reason).strip()
                if reason:
                    data["reasons"].append(reason)
        if "牌子" in line or "数量" in line:
            in_items = True; continue
        if "借货原因" in line or "原因" in line:
            in_items = False; continue
        if in_items and line and "per ctn" not in ll and "牌子" not in line:
            if not any(line.lower().startswith(k) for k in ["from","to","date","sender","account","cc"]):
                data["items"].append(line.strip())

    if not data["date"]:
        data["date"] = datetime.now().strftime("%d/%m/%y")
    return data


def build_status_text(data: dict, step: str, receiver_name: str = "", approver_name: str = "") -> str:
    items_str   = "\n".join(f"  • {it}" for it in data.get("items", [])) or "  —"
    reasons_str = "、".join(data.get("reasons", [])) or "—"
    base = (
        f"📦 *转货申请*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*发货方：* {data.get('from','?')}\n"
        f"*收货方：* {data.get('to','?')}\n"
        f"*日期：* {data.get('date','?')}\n"
        f"*货品：*\n{items_str}\n"
        f"*原因：* {reasons_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if step == "waiting_receiver":
        base += f"⏳ 等待 *{data.get('to','收货方')}* 确认收货..."
    elif step == "waiting_approval":
        base += f"✅ *{receiver_name}* 已确认收货\n⏳ 等待主管审批..."
    elif step == "approved":
        base += f"✅ *{receiver_name}* 已确认收货\n✅ *已批准* — {approver_name}"
    elif step == "rejected":
        base += f"✅ *{receiver_name}* 已确认收货\n❌ *已拒绝* — {approver_name}"
    elif step == "rejected_before_receive":
        base += f"❌ *已拒绝* — {approver_name}（收货前）"
    return base


# ── Auto-collect members ───────────────────────────────────────────────────────
async def auto_collect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Silently record user IDs for everyone who chats."""
    msg = update.message
    if not msg or not msg.from_user:
        return
    user = msg.from_user
    # Only record non-bots
    if user.is_bot:
        return
    members = load_members()
    uname = (user.username or "").lower()
    # Check if already registered by user_id
    for info in members.values():
        if info.get("user_id") == user.id:
            # Update username if changed
            if uname and info.get("username") != uname:
                info["username"] = uname
                save_members(members)
            return
    # Check if pre-loaded by username — fill in user_id
    if uname:
        for info in members.values():
            if info.get("username","").lower() == uname and not info.get("user_id"):
                info["user_id"] = user.id
                save_members(members)
                logger.info(f"Auto-linked {uname} → user_id {user.id}")
                return


# ── /register ──────────────────────────────────────────────────────────────────
async def register(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not ctx.args:
        await update.message.reply_text(
            "📝 请输入你的名字：\n`/register 你的名字`\n\n例如：`/register Jacky`",
            parse_mode="Markdown"
        )
        return
    name = " ".join(ctx.args).strip().lower()
    members = load_members()
    members[name] = {
        "user_id": user.id,
        "username": (user.username or "").lower(),
        "display_name": " ".join(ctx.args).strip().upper()
    }
    save_members(members)
    await update.message.reply_text(
        f"✅ 注册成功！\n名字：*{' '.join(ctx.args).strip().upper()}*\n已与你的账号绑定。",
        parse_mode="Markdown"
    )
    logger.info(f"Registered: {name} → {user.id} @{user.username}")


# ── /members ───────────────────────────────────────────────────────────────────
async def show_members(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_approver(update.effective_user):
        await update.message.reply_text("⛔ 只有主管可以查看成员列表。")
        return
    members = load_members()
    registered   = [(n,i) for n,i in members.items() if i.get("user_id")]
    unregistered = [(n,i) for n,i in members.items() if not i.get("user_id")]
    lines = ["*已注册成员：*"]
    for name, info in sorted(registered):
        uname = f"@{info['username']}" if info.get("username") else "（无用户名）"
        lines.append(f"  ✅ {info.get('display_name', name.upper())} — {uname}")
    if unregistered:
        lines.append("\n*未注册成员：*")
        for name, info in sorted(unregistered):
            lines.append(f"  ⏳ {info.get('display_name', name.upper())}")
    lines.append(f"\n_共 {len(registered)}/{len(members)} 人已注册_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Detect transfer ────────────────────────────────────────────────────────────
async def detect_transfer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    # Auto-collect user first
    await auto_collect(update, ctx)

    data = parse_transfer(msg.text)
    if not data:
        return

    logger.info(f"检测到转货申请: {data['from']} → {data['to']}")

    pending = ctx.bot_data.setdefault("pending", {})
    pending[str(msg.message_id)] = {
        **data,
        "submitter": msg.from_user.username or msg.from_user.first_name,
        "submitter_id": msg.from_user.id,
        "step": "waiting_receiver",
        "receiver_confirmed_by": "",
    }

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"📬 {data.get('to','收货方')} — 确认收货",
            callback_data=f"received_{msg.message_id}"
        )
    ]])

    await msg.reply_text(
        build_status_text(data, "waiting_receiver"),
        parse_mode="Markdown",
        reply_markup=keyboard
    )


# ── Receiver confirms ──────────────────────────────────────────────────────────
async def handle_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user  = query.from_user
    _, orig_msg_id = query.data.split("_", 1)

    pending = ctx.bot_data.setdefault("pending", {})
    record  = pending.get(orig_msg_id)

    if not record:
        await query.answer("❌ 找不到此申请记录。", show_alert=True)
        return

    to_field = record.get("to", "")

    if not is_receiver(user, to_field):
        await query.answer(
            f"⛔ 只有 {to_field} 才可以确认收货！",
            show_alert=True
        )
        return

    receiver_name = f"@{user.username}" if user.username else user.first_name
    record["step"] = "waiting_approval"
    record["receiver_confirmed_by"] = receiver_name

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ 批准", callback_data=f"approve_{orig_msg_id}"),
        InlineKeyboardButton("❌ 拒绝", callback_data=f"reject_{orig_msg_id}"),
    ]])

    await query.edit_message_text(
        build_status_text(record, "waiting_approval", receiver_name=receiver_name),
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    await query.answer("✅ 收货已确认！等待主管审批。")


# ── Approve / Reject ───────────────────────────────────────────────────────────
async def handle_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user  = query.from_user

    if not is_approver(user):
        await query.answer("⛔ 只有主管/经理可以审批。", show_alert=True)
        return

    action, orig_msg_id = query.data.split("_", 1)
    approver_name = f"@{user.username}" if user.username else user.first_name

    pending = ctx.bot_data.setdefault("pending", {})
    record  = pending.get(orig_msg_id)

    if not record:
        await query.answer("❌ 找不到此申请记录。", show_alert=True)
        return

    if action == "approve" and not record.get("receiver_confirmed_by"):
        await query.answer("⚠️ 收货方尚未确认收货，无法批准！", show_alert=True)
        return

    pending.pop(orig_msg_id, None)

    receiver_name = record.get("receiver_confirmed_by", "—")
    step = "approved" if action == "approve" else (
        "rejected" if record.get("receiver_confirmed_by") else "rejected_before_receive"
    )

    record["decision"]   = "已批准 ✅" if action == "approve" else "已拒绝 ❌"
    record["approver"]   = approver_name
    record["decided_at"] = datetime.now().isoformat()
    if action == "approve":
        record["autocount_done"] = False

    history = load_history()
    history.insert(0, record)
    save_history(history[:500])

    # 自动推送到 GitHub
    try:
        import json as _json
        await push_to_github(
            _json.dumps(history[:500], ensure_ascii=False, indent=2),
            "history.json",
            f"转货记录更新 {record.get('from','?')} → {record.get('to','?')} {record.get('decision','')}"
        )
    except Exception as e:
        logger.warning(f"推送失败: {e}")

    await query.edit_message_text(
        build_status_text(record, step, receiver_name=receiver_name, approver_name=approver_name),
        parse_mode="Markdown"
    )
    await query.answer("✅ 已批准！" if action == "approve" else "❌ 已拒绝！")

    # 通知发货方
    try:
        sid = record.get("submitter_id")
        if sid:
            verdict = "已批准 ✅" if action == "approve" else "已拒绝 ❌"
            await ctx.bot.send_message(
                chat_id=sid,
                text=f"你的转货申请（*{record.get('from','?')} → {record.get('to','?')}*）已被 {approver_name} *{verdict}*。",
                parse_mode="Markdown"
            )
    except Exception:
        pass

    # 通知账务
    if action == "approve" and ACCOUNTS_CHAT_ID:
        try:
            items_str   = "\n".join(f"  • {it}" for it in record.get("items", []))
            reasons_str = "、".join(record.get("reasons", []))
            await ctx.bot.send_message(
                chat_id=ACCOUNTS_CHAT_ID,
                text=(
                    f"✅ *已批准转货 — 请更新AutoCount*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"*发货方：* {record.get('from','?')}\n"
                    f"*收货方：* {record.get('to','?')}\n"
                    f"*日期：* {record.get('date','?')}\n\n"
                    f"*货品：*\n{items_str or '—'}\n\n"
                    f"*原因：* {reasons_str or '—'}\n"
                    f"*收货确认：* {receiver_name}\n"
                    f"*审批人：* {approver_name}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"_请更新AutoCount后在仪表板标记完成。_"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"无法通知账务: {e}")


# ── /dashboard ─────────────────────────────────────────────────────────────────
async def show_dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args    = ctx.args
    records = load_history()
    if not records:
        await update.message.reply_text("暂无转货记录。")
        return

    filter_str = " ".join(args).strip().lower() if args else ""
    def match(r):
        if not filter_str: return True
        return filter_str in (r.get("date","") + " " + r.get("decided_at","")).lower()

    filtered = [r for r in records if match(r)]
    pending  = [r for r in records if not r.get("decision")]
    ac_todo  = [r for r in records if r.get("autocount_done") is False]
    total    = len(filtered)
    approved = sum(1 for r in filtered if "批准" in r.get("decision",""))
    rejected = sum(1 for r in filtered if "拒绝" in r.get("decision",""))
    rate     = round(approved/total*100) if total else 0

    sku: dict = {}
    for r in filtered:
        if "批准" not in r.get("decision",""): continue
        for it in r.get("items", []):
            sku[it] = sku.get(it, 0) + 1
    top_skus  = sorted(sku.items(), key=lambda x: x[1], reverse=True)[:8]
    sku_lines = "\n".join(f"  {s:<14} {n}次" for s,n in top_skus) or "  —"

    agents: dict = {}
    for r in filtered:
        a = r.get("from","?"); agents[a] = agents.get(a,0)+1
    top_agents  = sorted(agents.items(), key=lambda x: x[1], reverse=True)[:5]
    agent_lines = "\n".join(f"  {i+1}. {a} — {n}次" for i,(a,n) in enumerate(top_agents))

    period = f"_{filter_str.upper()}_" if filter_str else "_全部记录_"
    await update.message.reply_text(
        f"📊 *转货仪表板* — {period}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 总申请数：*{total}*\n"
        f"✅ 已批准：*{approved}*（{rate}%）\n"
        f"❌ 已拒绝：*{rejected}*\n"
        f"⏳ 待处理：*{len(pending)}*\n"
        f"📋 待更新AutoCount：*{len(ac_todo)}*\n\n"
        f"*发货最多的人员*\n{agent_lines or '  —'}\n\n"
        f"*货品转移记录（已批准）*\n`{sku_lines}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"_用法：/dashboard [月份] 例如 /dashboard Apr_",
        parse_mode="Markdown"
    )


# ── /history ───────────────────────────────────────────────────────────────────
async def show_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    records = load_history()[:10]
    if not records:
        await update.message.reply_text("暂无转货记录。")
        return
    lines = []
    for r in records:
        items = "、".join(r.get("items", [])) or "—"
        recv  = r.get("receiver_confirmed_by", "—")
        lines.append(
            f"*{r.get('from','?')} → {r.get('to','?')}*（{r.get('date','?')}）\n"
            f"  货品：{items}\n"
            f"  收货确认：{recv}\n"
            f"  {r.get('decision','待处理')} — {r.get('approver','—')}"
        )
    await update.message.reply_text(
        "📋 *最近转货记录*\n\n" + "\n\n".join(lines),
        parse_mode="Markdown"
    )


# ── /start ─────────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *奇迹转货机器人*\n\n"
        "*使用流程：*\n"
        "1️⃣ 发货方在群里贴转货模板\n"
        "2️⃣ 收货方点击 📬 确认收货\n"
        "3️⃣ 主管点击 ✅ 批准 或 ❌ 拒绝\n"
        "4️⃣ 账务更新 AutoCount\n\n"
        "*指令：*\n"
        "/register 你的名字 — 注册账号\n"
        "/dashboard — 数据统计\n"
        "/history — 最近10条记录\n"
        "/members — 查看成员列表（主管）",
        parse_mode="Markdown"
    )


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("members", show_members))
    app.add_handler(CommandHandler("history", show_history))
    app.add_handler(CommandHandler("dashboard", show_dashboard))
    app.add_handler(CallbackQueryHandler(handle_received, pattern="^received_"))
    app.add_handler(CallbackQueryHandler(handle_decision, pattern="^(approve|reject)_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, detect_transfer))
    logger.info("机器人已启动，正在监听消息...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
