"""
Miracle Transfer Bot
====================
Telegram bot for GRP 2A stock transfer requests.
Agents submit via guided conversation, approvers tap inline buttons.
"""

import os
import json
import logging
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GROUP_ID    = int(os.environ.get("GROUP_ID", "0"))   # your Telegram group chat ID (negative number)
HISTORY_FILE = "history.json"

# Approver Telegram usernames (lowercase, no @) — edit this list
APPROVER_USERNAMES = set(os.environ.get("APPROVERS", "").lower().split(","))
# Approver roles label shown in messages
APPROVER_ROLES = "MD / Supervisor / Area Manager / Accounts"
# Accounts dept Telegram chat ID (user or group) — gets notified on every approval
ACCOUNTS_CHAT_ID = int(os.environ.get("ACCOUNTS_CHAT_ID", "0"))

# Reason options
REASONS = ["过货", "清货", "代替送货", "借货", "紧急补货"]

# Conversation states
(
    FROM_AGENT, TO_AGENT, ITEMS, MORE_ITEMS, REASON, CONFIRM
) = range(6)


# ── History helpers ───────────────────────────────────────────────────────────
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return []

def save_history(records):
    with open(HISTORY_FILE, "w") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


# ── Permission check ──────────────────────────────────────────────────────────
def is_approver(user) -> bool:
    """Returns True if user is allowed to approve/reject."""
    if not APPROVER_USERNAMES or APPROVER_USERNAMES == {""}:
        return True  # no restriction configured — allow all
    uname = (user.username or "").lower()
    return uname in APPROVER_USERNAMES


# ── Format message ────────────────────────────────────────────────────────────
def format_request(data: dict) -> str:
    items_str = "\n".join(f"  • {it['brand']} — {it['qty']} ctn" for it in data["items"])
    reasons_str = "\n".join(
        f"  {i+1}. {r} {'✅' if r in data['reasons'] else ''}"
        for i, r in enumerate(REASONS)
    )
    date_str = data.get("date", datetime.now().strftime("%-d/%-m/%y"))
    return (
        f"📦 *Stock Transfer Request*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*From :* {data['from']}\n"
        f"*To   :* {data['to']}\n"
        f"*Date :* {date_str}\n\n"
        f"*牌子 & 数量 (Per ctn)*\n{items_str}\n\n"
        f"*借货原因*\n{reasons_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"_Submitted by @{data['submitter']}_"
    )


# ── /start ────────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Miracle Transfer Bot*\n\n"
        "Use /transfer to submit a stock transfer request.\n"
        "Use /history to view recent decisions.\n"
        "Use /cancel to cancel anytime.",
        parse_mode="Markdown"
    )


# ── /transfer conversation ────────────────────────────────────────────────────
async def transfer_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["items"] = []
    await update.message.reply_text(
        "📦 *New Transfer Request*\n\nStep 1/5 — Who is *sending* the stock?\n_(Type the agent name)_",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return FROM_AGENT

async def got_from(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["from"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ From: *{ctx.user_data['from']}*\n\nStep 2/5 — Who is *receiving* the stock?",
        parse_mode="Markdown"
    )
    return TO_AGENT

async def got_to(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["to"] = update.message.text.strip()
    ctx.user_data["date"] = datetime.now().strftime("%-d/%-m/%y")
    await update.message.reply_text(
        f"✅ To: *{ctx.user_data['to']}*\n\n"
        "Step 3/5 — Add items one by one.\n"
        "Format: `BRAND QTY` (e.g. `TR-45 3` or `EVO-55 2`)\n"
        "Type each item and press send. When done, type *done*.",
        parse_mode="Markdown"
    )
    return ITEMS

async def got_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "done":
        if not ctx.user_data["items"]:
            await update.message.reply_text("⚠️ Please add at least one item first.")
            return ITEMS
        return await ask_reason(update, ctx)
    # parse "BRAND QTY"
    parts = text.split()
    if len(parts) < 2 or not parts[-1].isdigit():
        await update.message.reply_text(
            "⚠️ Format: `BRAND QTY` e.g. `TR-45 3`\nTry again or type *done* to proceed.",
            parse_mode="Markdown"
        )
        return ITEMS
    qty = parts[-1]
    brand = " ".join(parts[:-1]).upper()
    ctx.user_data["items"].append({"brand": brand, "qty": qty})
    items_so_far = "\n".join(f"  • {it['brand']} — {it['qty']} ctn" for it in ctx.user_data["items"])
    await update.message.reply_text(
        f"✅ Added *{brand}* — {qty} ctn\n\n*Items so far:*\n{items_so_far}\n\nAdd more or type *done*.",
        parse_mode="Markdown"
    )
    return ITEMS

async def ask_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"{'✅ ' if r in ctx.user_data.get('reasons', []) else ''}{r}", callback_data=f"reason_{r}")]
        for r in REASONS
    ] + [[InlineKeyboardButton("➡️ Confirm Reasons", callback_data="reason_done")]]
    ctx.user_data.setdefault("reasons", [])
    await update.message.reply_text(
        "Step 4/5 — Select *reason(s)* (tap to toggle, then confirm):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REASON

async def got_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "reason_done":
        if not ctx.user_data.get("reasons"):
            await query.answer("⚠️ Select at least one reason.", show_alert=True)
            return REASON
        return await show_confirm(query, ctx)

    reason = data.replace("reason_", "")
    reasons = ctx.user_data.setdefault("reasons", [])
    if reason in reasons:
        reasons.remove(reason)
    else:
        reasons.append(reason)

    # Refresh keyboard
    keyboard = [
        [InlineKeyboardButton(f"{'✅ ' if r in reasons else ''}{r}", callback_data=f"reason_{r}")]
        for r in REASONS
    ] + [[InlineKeyboardButton("➡️ Confirm Reasons", callback_data="reason_done")]]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    return REASON

async def show_confirm(query, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["submitter"] = query.from_user.username or query.from_user.first_name
    preview = format_request(ctx.user_data)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Edit (restart)", callback_data="confirm_restart"),
            InlineKeyboardButton("📤 Submit", callback_data="confirm_submit"),
        ]
    ])
    await query.edit_message_text(
        f"Step 5/5 — *Review your request:*\n\n{preview}\n\nLooks good?",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    return CONFIRM

async def got_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_restart":
        await query.edit_message_text("❌ Cancelled. Use /transfer to start again.")
        return ConversationHandler.END

    # Post to group
    data = ctx.user_data.copy()
    msg_text = format_request(data)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{query.from_user.id}"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"reject_{query.from_user.id}"),
        ]
    ])

    try:
        group_msg = await ctx.bot.send_message(
            chat_id=GROUP_ID,
            text=msg_text + f"\n\n_{APPROVER_ROLES} may approve._",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        # Store pending request keyed by group message id
        pending = ctx.bot_data.setdefault("pending", {})
        pending[str(group_msg.message_id)] = data

        await query.edit_message_text(
            "✅ *Request submitted to the group!*\nYou'll be notified when it's approved or rejected.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send to group: {e}")
        await query.edit_message_text(
            f"⚠️ Could not post to group. Ask admin to check GROUP_ID setting.\n`{e}`",
            parse_mode="Markdown"
        )

    return ConversationHandler.END


# ── Approve / Reject callback ─────────────────────────────────────────────────
async def handle_decision(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    if not is_approver(user):
        await query.answer(f"⛔ Only {APPROVER_ROLES} can approve/reject.", show_alert=True)
        return

    action, submitter_id = query.data.split("_", 1)
    decision = "APPROVED ✅" if action == "approve" else "REJECTED ❌"
    approver_name = f"@{user.username}" if user.username else user.first_name

    # Update group message — remove buttons, add decision stamp
    original = query.message.text or ""
    new_text = original.split("\n\n_")[0]  # strip old footer
    new_text += f"\n\n{'✅' if action == 'approve' else '❌'} *{decision}*\nBy {approver_name} · {datetime.now().strftime('%-d/%-m/%y %H:%M')}"

    await query.edit_message_text(new_text, parse_mode="Markdown")

    # Save to history
    pending = ctx.bot_data.get("pending", {})
    msg_id = str(query.message.message_id)
    record = pending.pop(msg_id, {})
    record["decision"] = decision
    record["approver"] = approver_name
    record["decided_at"] = datetime.now().isoformat()
    if action == "approve":
        record["autocount_done"] = False  # accounts will mark this True

    history = load_history()
    history.insert(0, record)
    save_history(history[:200])  # keep last 200

    await query.answer(f"{decision} recorded!")

    # Notify submitter in DM if possible
    try:
        await ctx.bot.send_message(
            chat_id=int(submitter_id),
            text=f"Your transfer request (*{record.get('from','?')} → {record.get('to','?')}*) was *{decision}* by {approver_name}.",
            parse_mode="Markdown"
        )
    except Exception:
        pass  # DM notification is best-effort

    # Notify accounts dept on approval
    if action == "approve" and ACCOUNTS_CHAT_ID:
        try:
            items_str = "\n".join(f"  • {it['brand']} — {it['qty']} ctn" for it in record.get("items", []))
            reasons_str = ", ".join(record.get("reasons", []))
            acct_msg = (
                f"✅ *New Approved Transfer — Action Required*\n"
                f"──────────────────────\n"
                f"*From:* {record.get('from','?')}\n"
                f"*To:*   {record.get('to','?')}\n"
                f"*Date:* {record.get('date','?')}\n\n"
                f"*Items to transfer in AutoCount:*\n{items_str}\n\n"
                f"*Reason:* {reasons_str}\n"
                f"*Approved by:* {approver_name}\n"
                f"──────────────────────\n"
                f"_Please update AutoCount and mark done in dashboard._"
            )
            await ctx.bot.send_message(
                chat_id=ACCOUNTS_CHAT_ID,
                text=acct_msg,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Could not notify accounts: {e}")


# ── /history command ──────────────────────────────────────────────────────────
async def show_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    records = load_history()[:10]
    if not records:
        await update.message.reply_text("No transfer history yet.")
        return
    lines = []
    for r in records:
        items = ", ".join(f"{it['brand']}×{it['qty']}" for it in r.get("items", []))
        lines.append(
            f"*{r.get('from','?')} → {r.get('to','?')}* ({r.get('date','?')})\n"
            f"  {items}\n"
            f"  {r.get('decision','?')} by {r.get('approver','?')}"
        )
    await update.message.reply_text(
        "📋 *Recent Transfers (last 10)*\n\n" + "\n\n".join(lines),
        parse_mode="Markdown"
    )


# ── /dashboard command ─────────────────────────────────────────────────────────
async def show_dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Send a quick summary stats message. Optionally filter by month: /dashboard Mar"""
    args = ctx.args
    records = load_history()
    if not records:
        await update.message.reply_text("No transfer history yet.")
        return

    # Optional month filter e.g. /dashboard Mar or /dashboard Mar 26
    filter_str = " ".join(args).strip().lower() if args else ""

    def match_month(r):
        if not filter_str:
            return True
        date_val = r.get("date", "") or ""
        decided = r.get("decided_at", "") or ""
        combined = (date_val + " " + decided).lower()
        return filter_str in combined

    filtered = [r for r in records if match_month(r)]
    pending  = [r for r in records if not r.get("decision")]

    total    = len(filtered)
    approved = sum(1 for r in filtered if r.get("decision","").upper().startswith("APPROVED"))
    rejected = sum(1 for r in filtered if r.get("decision","").upper().startswith("REJECTED"))
    rate     = round(approved / total * 100) if total else 0

    # Top senders
    agent_count: dict = {}
    for r in filtered:
        a = r.get("from", "?")
        agent_count[a] = agent_count.get(a, 0) + 1
    top_agents = sorted(agent_count.items(), key=lambda x: x[1], reverse=True)[:5]
    top_lines  = "\n".join(f"  {i+1}. {a} — {n} transfer{'s' if n>1 else ''}" for i, (a, n) in enumerate(top_agents))

    # Top reasons
    reason_count: dict = {}
    for r in filtered:
        for rs in r.get("reasons", []):
            reason_count[rs] = reason_count.get(rs, 0) + 1
    top_reasons = sorted(reason_count.items(), key=lambda x: x[1], reverse=True)[:3]
    reason_lines = " · ".join(f"{rs} ({n})" for rs, n in top_reasons) or "—"

    # SKU summary (approved transfers only)
    sku_count: dict = {}
    for r in filtered:
        if r.get("decision", "").upper().startswith("APPROVED"):
            for it in r.get("items", []):
                brand = it.get("brand", "?").upper()
                try:
                    qty = int(it.get("qty", 0))
                except (ValueError, TypeError):
                    qty = 0
                if brand not in sku_count:
                    sku_count[brand] = {"ctn": 0, "times": 0}
                sku_count[brand]["ctn"] += qty
                sku_count[brand]["times"] += 1
    top_skus = sorted(sku_count.items(), key=lambda x: x[1]["ctn"], reverse=True)[:8]
    sku_lines = "\n".join(
        f"  {s:<10} {v['ctn']:>4} ctn  ({v['times']}x)" for s, v in top_skus
    ) or "  —"

    # Pending AutoCount (approved but not yet done)
    ac_pending = [r for r in records if r.get("autocount_done") is False]

    period_label = f"_{filter_str.title()}_" if filter_str else "_All time_"
    msg = (
        f"📊 *Transfer Dashboard* — {period_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Total Requests : *{total}*\n"
        f"✅ Approved       : *{approved}* ({rate}%)\n"
        f"❌ Rejected       : *{rejected}*\n"
        f"⏳ Pending        : *{len(pending)}*\n"
        f"📋 AutoCount todo  : *{len(ac_pending)}*\n\n"
        f"*Top Agents (transfers out)*\n{top_lines or '  —'}\n\n"
        f"*SKU Movement (approved, {period_label})*\n"
        f"`{'SKU':<10} {'CTN':>4}  (times)`\n"
        f"`{sku_lines}`\n\n"
        f"*Common Reasons*\n  {reason_lines}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"_Use /dashboard [month] e.g. /dashboard Mar_"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# ── /cancel ───────────────────────────────────────────────────────────────────
async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("transfer", transfer_start)],
        states={
            FROM_AGENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_from)],
            TO_AGENT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_to)],
            ITEMS:      [MessageHandler(filters.TEXT & ~filters.COMMAND, got_item)],
            REASON:     [CallbackQueryHandler(got_reason, pattern="^reason_")],
            CONFIRM:    [CallbackQueryHandler(got_confirm, pattern="^confirm_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", show_history))
    app.add_handler(CommandHandler("dashboard", show_dashboard))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(handle_decision, pattern="^(approve|reject)_"))

    logger.info("Bot started. Polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
