"""
Reminder Log Module
===================
Generates Telegram-style compliance reminders based on upcoming deadlines,
simulates sending them, and maintains logs.
"""

import os
from datetime import datetime
import pandas as pd

def generate_reminder_messages(upcoming_df):
    """
    Generates tailored reminder messages based on the days remaining until a deadline.
    
    Args:
        upcoming_df: DataFrame containing upcoming or overdue compliance records.
        
    Returns:
        List of dictionaries with message details and urgency levels.
    """
    messages = []
    
    if upcoming_df is None or upcoming_df.empty:
        return messages
        
    for _, row in upcoming_df.iterrows():
        client_id = row.get("client_id", "")
        client_name = row.get("client_name", "")
        ctype = row.get("compliance_type", "")
        due_date = row.get("due_date", "")
        
        try:
            days = int(row.get("days_until_due", 0))
        except (ValueError, TypeError):
            continue
            
        try:
            penalty = float(row.get("penalty_per_day", 0.0))
        except (ValueError, TypeError):
            penalty = 0.0
            
        # Format penalty to avoid decimals if not needed
        penalty_str = f"{penalty:g}"
            
        message = ""
        urgency_level = ""
        
        if days == 7:
            message = f"⚠️ REMINDER: {client_name} — {ctype} is due in 7 days on {due_date}. Penalty: ₹{penalty_str}/day if missed. Please file at the earliest."
            urgency_level = "week_7day"
        elif days == 1:
            message = f"🚨 URGENT: {client_name} — {ctype} is due TOMORROW ({due_date}). File today to avoid penalty of ₹{penalty_str}/day."
            urgency_level = "urgent_1day"
        elif days <= 0:
            message = f"🔴 OVERDUE: {client_name} — {ctype} was due on {due_date}. Days overdue: {abs(days)}. Escalate immediately."
            urgency_level = "overdue"
        else:
            continue  # Skip rows that don't match exact target days
            
        messages.append({
            "client_id": client_id,
            "client_name": client_name,
            "compliance_type": ctype,
            "due_date": due_date,
            "days_until_due": days,
            "message": message,
            "urgency_level": urgency_level
        })
        
    return messages


def simulate_telegram_send(message_dict):
    """
    Simulates sending a Telegram message by writing to a local log file.
    
    Args:
        message_dict: A single dictionary from the list returned by generate_reminder_messages.
        
    Returns:
        Dict with send status and timestamp.
    """
    # Create log file in project root or data dir
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_file = os.path.join(project_root, "data", "reminder_log.txt")
    
    now = datetime.now().isoformat()
    
    log_entry = f"[{now}] TO: {message_dict.get('client_id')} | MSG: {message_dict.get('message')}\n"
    
    # Append to the file (utf-8 to safely handle emoji writing)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(log_entry)
        
    return {
        "status": "sent",
        "timestamp": now,
        "message": message_dict
    }


def get_reminder_summary(messages_list):
    """
    Generates a summary of reminder volumes by urgency.
    
    Args:
        messages_list: List of message dictionaries.
        
    Returns:
        Dict with count totals for each category.
    """
    total = len(messages_list)
    urgent_1day = sum(1 for m in messages_list if m.get("urgency_level") == "urgent_1day")
    week_7day = sum(1 for m in messages_list if m.get("urgency_level") == "week_7day")
    overdue = sum(1 for m in messages_list if m.get("urgency_level") == "overdue")
    
    return {
        "total": total,
        "urgent_1day": urgent_1day,
        "week_7day": week_7day,
        "overdue": overdue
    }

if __name__ == "__main__":
    print("=" * 50)
    print("  REMINDER LOG - Test Run")
    print("=" * 50)
    
    # Create dummy dataframe to test
    dummy_data = [
        {"client_id": "CL-001", "client_name": "Acme Corp", "compliance_type": "GSTR-3B", "due_date": "2026-05-07", "days_until_due": 7, "penalty_per_day": 50},
        {"client_id": "CL-002", "client_name": "Globex", "compliance_type": "PF Challan", "due_date": "2026-05-01", "days_until_due": 1, "penalty_per_day": 0},
        {"client_id": "CL-003", "client_name": "Initech", "compliance_type": "TDS Return", "due_date": "2026-04-20", "days_until_due": -10, "penalty_per_day": 200},
        {"client_id": "CL-004", "client_name": "Umbrella", "compliance_type": "ESIC", "due_date": "2026-05-05", "days_until_due": 5, "penalty_per_day": 0}  # Should be skipped
    ]
    df = pd.DataFrame(dummy_data)
    
    messages = generate_reminder_messages(df)
    
    print(f"\nGenerated Messages ({len(messages)} out of {len(df)} rows):")
    for msg in messages:
        # Use ascii encode to avoid printing emoji errors in basic consoles
        try:
            print(f"\n{msg['message']}")
        except UnicodeEncodeError:
            print(f"\n{msg['message'].encode('ascii', 'replace').decode('ascii')}")
            
        res = simulate_telegram_send(msg)
        print(f" -> Simulate status: {res['status']} at {res['timestamp']}")
        
    summary = get_reminder_summary(messages)
    print("\nSummary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
