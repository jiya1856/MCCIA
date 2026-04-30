import streamlit as st
import pandas as pd
import os
from datetime import datetime
from dotenv import load_dotenv

# Set page config
st.set_page_config(
    page_title="⚖️ Mehta & Associates — Compliance Co-pilot",
    page_icon="⚖️",
    layout="wide"
)

# Load environment variables
load_dotenv(override=True)

# --- Imports from modules ---
from modules import load_all_data
from modules.deadline_tracker import (
    build_deadline_matrix,
    validate_against_missed_log,
    get_upcoming_reminders
)
from modules.qa_engine import answer_question
from modules.gstr_generator import generate_gstr3b, gstr3b_to_dataframe
from modules.reminder_log import (
    generate_reminder_messages,
    simulate_telegram_send,
    get_reminder_summary
)

# --- Session State Init ---
if 'qa_history' not in st.session_state:
    st.session_state.qa_history = []
if 'current_question' not in st.session_state:
    st.session_state.current_question = ""

def set_question(q):
    st.session_state.current_question = q

# --- Data Loading ---
@st.cache_data
def get_cached_data():
    return load_all_data()

try:
    data = get_cached_data()
    profiles = data.client_profiles
    calendar = data.compliance_calendar
    missed = data.missed_deadlines
    circulars = data.gst_circulars
    # Initialize matrix
    matrix_df = build_deadline_matrix(profiles, calendar)
    validation = validate_against_missed_log(matrix_df, missed)
except Exception as e:
    st.error(f"Error loading data: {e}")
    st.stop()

# --- Sidebar ---
st.sidebar.title("⚖️ Mehta & Associates")
st.sidebar.markdown("**Compliance Co-pilot**")
st.sidebar.image("https://via.placeholder.com/150x150.png?text=Firm+Logo", width=100)
st.sidebar.divider()
st.sidebar.metric("Total Clients", len(profiles) if profiles is not None else 0)
st.sidebar.write(f"**Today's Date:** {datetime.now().strftime('%d %b %Y')}")
st.sidebar.write(f"**Data last refreshed:** {datetime.now().strftime('%H:%M:%S')}")

# --- Tabs ---
tab1, tab2, tab3, tab4 = st.tabs([
    "📅 Deadline Tracker",
    "🤖 Q&A Assistant",
    "📄 GSTR-3B Generator",
    "🔔 Reminder Log"
])

# ============================================================
# TAB 1: Deadline Tracker
# ============================================================
with tab1:
    st.header("Compliance Deadline Tracker")
    
    # Validation Banner
    detected = validation.get("detected", 0)
    total = validation.get("total", 11)
    if detected == total:
        st.success(f"✅ {detected}/{total} historical missed deadlines detected by system")
    else:
        st.warning(f"⚠️ {detected}/{total} historical missed deadlines detected by system")
        
    # Metrics
    if not matrix_df.empty:
        overdue_count = len(matrix_df[matrix_df['status'] == 'OVERDUE'])
        soon_count = len(matrix_df[matrix_df['status'].isin(['DUE_SOON_1', 'DUE_SOON_7'])])
    else:
        overdue_count = 0
        soon_count = 0
        
    col1, col2, col3 = st.columns(3)
    col1.metric("Total clients", len(profiles))
    col2.metric("Overdue deadlines", overdue_count)
    col3.metric("Due in next 7 days", soon_count)
    
    st.divider()
    
    # Filter
    days_filter = st.slider("Show next [X] days", min_value=7, max_value=90, value=30)
    
    if not matrix_df.empty:
        # Filter dataframe
        display_df = matrix_df[matrix_df['days_until_due'] <= days_filter].copy()
        
        # Styler function
        def style_status(val):
            if val == "OVERDUE":
                return "background-color: #ffcccc; color: #cc0000; font-weight: bold;"
            elif "DUE_SOON" in str(val):
                return "background-color: #ffffcc; color: #cccc00; font-weight: bold;"
            elif val == "SAFE":
                return "background-color: #ccffcc; color: #008000; font-weight: bold;"
            return ""
            
        styled_df = display_df.style.map(style_status, subset=['status'])
        
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
        
        # Download
        csv = display_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Full Schedule",
            data=csv,
            file_name="compliance_schedule.csv",
            mime="text/csv"
        )
    else:
        st.info("Matrix is empty. No deadlines found within the 60-day window.")


# ============================================================
# TAB 2: Q&A Assistant
# ============================================================
with tab2:
    st.header("AI Compliance Assistant")
    
    # Example Questions
    st.write("**Suggested Questions:**")
    eq_cols = st.columns(2)
    examples = [
        "What is the penalty for late PF deposit?",
        "Can I file GSTR-1 after the due date?",
        "What happens if ESIC contribution is delayed?",
        "What is the late fee for GSTR-3B?"
    ]
    for i, ex in enumerate(examples):
        with eq_cols[i % 2]:
            st.button(ex, on_click=set_question, args=(ex,))
            
    # Text input
    question = st.text_input("Ask a compliance question...", value=st.session_state.current_question)
    
    if st.button("Submit Question", type="primary"):
        if question:
            with st.spinner("Analyzing regulations and circulars..."):
                result = answer_question(question, circulars)
                
                st.session_state.qa_history.insert(0, {
                    "question": question,
                    "result": result
                })
                
                # Display Current Answer
                st.markdown("### Answer")
                st.info(result['answer'])
                
                # Badges
                col_b1, col_b2 = st.columns(2)
                if result['has_citation']:
                    col_b1.success("✓ Citation found")
                else:
                    col_b1.error("✗ No citation")
                    
                # Warning
                if result.get('superseded_warning'):
                    st.warning(result['superseded_warning'])
                    
                st.caption(f"*{'This is not legal advice' if result['has_disclaimer'] else ''}*")
                
                # Clear current question from input after answering
                st.session_state.current_question = ""

    # History
    if st.session_state.qa_history:
        st.divider()
        with st.expander("Recent Questions History"):
            for item in st.session_state.qa_history[:5]:
                st.markdown(f"**Q: {item['question']}**")
                st.write(item['result']['answer'])
                st.markdown("---")


# ============================================================
# TAB 3: GSTR-3B Generator
# ============================================================
with tab3:
    st.header("GSTR-3B Auto-Generator")
    st.write("Upload raw Tally CSV export files below.")
    
    col_upload1, col_upload2 = st.columns(2)
    with col_upload1:
        sales_file = st.file_uploader("Sales Register CSV (Required)", type=["csv"], key="sales")
    with col_upload2:
        purchase_file = st.file_uploader("Purchase Register CSV (Optional - for ITC)", type=["csv"], key="purchase")
        
    if st.button("Generate GSTR-3B Draft", type="primary"):
        if sales_file is not None:
            try:
                gstr3b_dict = generate_gstr3b(sales_file, purchase_file)
                st.success(f"✅ Processed {gstr3b_dict.get('source_row_count', 0)} source transactions")
                
                df_out = gstr3b_to_dataframe(gstr3b_dict)
                
                st.subheader("GSTR-3B Output")
                st.dataframe(df_out, use_container_width=True, hide_index=True)
                
                csv = df_out.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download GSTR-3B CSV",
                    data=csv,
                    file_name=f"gstr3b_draft_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
            except Exception as e:
                st.error(f"Error generating GSTR-3B: {str(e)}")
        else:
            st.warning("Please upload at least the Sales Register CSV.")


# ============================================================
# TAB 4: Reminder Log
# ============================================================
with tab4:
    st.header("Automated Reminder Hub")
    
    if not matrix_df.empty:
        upcoming_df = get_upcoming_reminders(matrix_df)
        messages = generate_reminder_messages(upcoming_df)
        summary = get_reminder_summary(messages)
    else:
        messages = []
        summary = {"total": 0, "urgent_1day": 0, "week_7day": 0, "overdue": 0}
        
    col_r1, col_r2, col_r3 = st.columns(3)
    col_r1.metric("Total reminders", summary["total"])
    col_r2.metric("1-day urgent", summary["urgent_1day"])
    col_r3.metric("7-day warnings", summary["week_7day"])
    
    st.divider()
    
    if messages:
        if st.button("Send All Reminders", type="primary"):
            sent_count = 0
            for msg in messages:
                res = simulate_telegram_send(msg)
                sent_count += 1
            st.success(f"✅ Successfully queued {sent_count} reminders.")
            
        st.subheader("Pending Reminders")
        # Display as a table with a send button
        for i, msg in enumerate(messages):
            with st.container(border=True):
                rcol1, rcol2, rcol3 = st.columns([1, 4, 1])
                rcol1.write(f"**{msg['client_name']}**\n\n{msg['compliance_type']}")
                
                # Color code message
                if msg['urgency_level'] == 'overdue':
                    rcol2.error(msg['message'])
                elif msg['urgency_level'] == 'urgent_1day':
                    rcol2.warning(msg['message'])
                else:
                    rcol2.info(msg['message'])
                    
                if rcol3.button("📤 Send Telegram", key=f"send_{i}_{msg['client_id']}"):
                    res = simulate_telegram_send(msg)
                    st.toast(f"✓ Message logged at {res['timestamp']}")
                    st.success(f"Sent at {datetime.fromisoformat(res['timestamp']).strftime('%H:%M:%S')}")
    else:
        st.info("No upcoming or overdue reminders to send.")
        
    st.divider()
    
    st.subheader("Reminder Log History")
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "reminder_log.txt")
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if lines:
            # Show last 20 entries
            for line in reversed(lines[-20:]):
                st.text(line.strip())
        else:
            st.write("Log file is empty.")
    else:
        st.write("No logs generated yet.")
