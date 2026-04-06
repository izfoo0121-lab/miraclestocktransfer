import re

with open("bot.py", "r") as f:
    src = f.read()

old = '''    # Save to history
    pending = ctx.bot_data.get("pending", {})
    msg_id = str(query.message.message_id)
    record = pending.pop(msg_id, {})
    record["decision"] = decision
    record["approver"] = approver_name
    record["decided_at"] = datetime.now().isoformat()

    history = load_history()
    history.insert(0, record)
    save_history(history[:200])  # keep last 200

    await query.answer(f"{decision} recorded!")

    # Notify submitter in DM if possible
    try:
        await ctx.bot.send_message(
            chat_id=int(submitter_id),
            text=f"Your transfer request (*{record.get(\'from\',\'?\')}\u00a0\u2192\u00a0{record.get(\'to\',\'?\')
}*) was *{decision}* by {approver_name}.",
            parse_mode="Markdown"
        )
    except Exception:
        pass  # DM notification is best-effort'''

print("old found:", old in src)
