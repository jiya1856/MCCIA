"""
Deadline Tracker Module
========================
Tracks compliance deadlines, identifies upcoming and overdue filings,
and generates alerts for Mehta & Associates' 68 MSME clients.

Functions:
    1. parse_due_date       - Parse text/date due_date descriptions into datetime
    2. get_client_applicable_compliances - Filter calendar rows by client eligibility
    3. build_deadline_matrix - Build client x compliance matrix with status flags
    4. validate_against_missed_log - Cross-check matrix against historical misses
    5. get_upcoming_reminders - Filter matrix to DUE_SOON items
"""

import re
import calendar
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# 1. parse_due_date
# ---------------------------------------------------------------------------

def parse_due_date(due_date_text, reference_month=None, reference_year=None):
    """
    Parse a due-date description into an actual datetime object.

    Handles formats found in the compliance calendar:
      - Actual dates: "21-04-2024", "15-02-2025"
      - Text rules:   "15th of following month", "30th of following month",
                       "31st of March", "15th June", "7th of same month"

    If the day exceeds the valid range for the target month (e.g. 31st Feb),
    the last day of that month is used instead.

    Args:
        due_date_text: The due-date string from the calendar.
        reference_month: Reference month (1-12) for relative descriptions.
        reference_year:  Reference year for relative descriptions.

    Returns:
        datetime object, or None if parsing fails.
    """
    if reference_month is None:
        reference_month = datetime.today().month
    if reference_year is None:
        reference_year = datetime.today().year

    text = str(due_date_text).strip()

    # --- Try actual date formats first ---
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    # --- Text-based rules (check BEFORE pandas to avoid year-0001 mangling) ---
    text_lower = text.lower()

    # Extract the day number from text (e.g. "15th", "31st", "7th")
    day_match = re.search(r"(\d{1,2})\s*(?:st|nd|rd|th)", text_lower)
    if day_match:
        day = int(day_match.group(1))

        # Determine target month and year
        target_month = reference_month
        target_year = reference_year

        if "following month" in text_lower or "next month" in text_lower:
            target_month = reference_month + 1
            if target_month > 12:
                target_month = 1
                target_year += 1
        elif "same month" in text_lower or "current month" in text_lower:
            pass  # keep reference month
        else:
            # Check for explicit month name: "31st of March", "15th June"
            month_names = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
            month_abbrs = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
            all_months = {**month_names, **month_abbrs}

            for name, num in all_months.items():
                if name in text_lower:
                    target_month = num
                    # If the named month is before the reference month, assume next year
                    if target_month < reference_month:
                        target_year += 1
                    break

        # Clamp day to the valid range for the target month
        max_day = calendar.monthrange(target_year, target_month)[1]
        day = min(day, max_day)

        return datetime(target_year, target_month, day)

    # --- Fallback: try pandas timestamp ---
    try:
        ts = pd.Timestamp(text)
        if not pd.isna(ts):
            return ts.to_pydatetime()
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# 2. get_client_applicable_compliances
# ---------------------------------------------------------------------------

def get_client_applicable_compliances(client_row, calendar_df):
    """
    Determine which compliance types from the calendar apply to a given client.

    Applicability rules:
      - ALL clients: GST (respecting filing_frequency), TDS, Income Tax,
        Professional Tax, Shop & Establishment
      - Only if pf_reg is filled:    PF-related compliances
      - Only if esic_reg is filled:  ESIC-related compliances
      - Only if fssai_reg is filled: FSSAI-related compliances
      - Only if iec_code is filled:  Import-Export compliances

    Filing frequency matching:
      - Monthly clients  -> get rows where frequency == 'monthly'
      - Quarterly clients -> get rows where frequency == 'quarterly'
      - Annual / other    -> all clients get these

    Args:
        client_row: A single row (pd.Series) from client_profiles.
        calendar_df: The full compliance_calendar_master DataFrame.

    Returns:
        List of calendar_df row indices (or the filtered DataFrame rows)
        representing applicable compliances.
    """
    filing_freq = str(client_row.get("filing_frequency", "")).strip().lower()
    has_pf = pd.notna(client_row.get("pf_reg")) and str(client_row.get("pf_reg")).strip() != ""
    has_esic = pd.notna(client_row.get("esic_reg")) and str(client_row.get("esic_reg")).strip() != ""
    has_fssai = pd.notna(client_row.get("fssai_reg")) and str(client_row.get("fssai_reg")).strip() != ""
    has_iec = pd.notna(client_row.get("iec_code")) and str(client_row.get("iec_code")).strip() != ""

    applicable_rows = []

    for idx, cal_row in calendar_df.iterrows():
        ctype = str(cal_row.get("compliance_type", "")).strip()
        freq = str(cal_row.get("frequency", "")).strip().lower()
        condition = str(cal_row.get("applicability_condition", "")).lower()

        # --- Registration-gated compliances ---
        # PF
        if "pf" in ctype.lower() or "pf registered" in condition:
            if not has_pf:
                continue

        # ESIC
        if "esic" in ctype.lower() or "esic registered" in condition:
            if not has_esic:
                continue

        # FSSAI
        if "fssai" in ctype.lower() or "fssai" in condition:
            if not has_fssai:
                continue

        # Import-Export / IEC
        if any(kw in ctype.lower() for kw in ("import", "export", "iec")):
            if "gstr" not in ctype.lower() and "income tax" not in ctype.lower():
                if not has_iec:
                    continue

        # --- Frequency matching for GST ---
        if "gstr" in ctype.lower():
            if "(monthly)" in ctype.lower() and filing_freq != "monthly":
                continue
            if "(quarterly)" in ctype.lower() and filing_freq != "quarterly":
                continue

        applicable_rows.append(cal_row)

    return applicable_rows


# ---------------------------------------------------------------------------
# 3. build_deadline_matrix
# ---------------------------------------------------------------------------

def build_deadline_matrix(profiles_df, calendar_df):
    """
    Build a full client x compliance deadline matrix.

    For every (client, applicable compliance) pair:
      - Parse the due_date from the calendar into an actual date
      - Compute days_until_due = (due_date - today).days
      - Assign status:
          'OVERDUE'      if days_until_due < 0
          'DUE_SOON_1'   if days_until_due == 1
          'DUE_SOON_7'   if 0 <= days_until_due <= 7
          'SAFE'         if days_until_due > 7

    Only includes deadlines within the window: past 90 days to next 60 days
    from today.

    Args:
        profiles_df: client_profiles DataFrame (68 rows).
        calendar_df: compliance_calendar_master DataFrame.

    Returns:
        DataFrame with columns:
            client_id, client_name, compliance_type, due_date,
            days_until_due, status, penalty_per_day
    """
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = today - timedelta(days=90)
    window_end = today + timedelta(days=60)

    rows = []

    for _, client in profiles_df.iterrows():
        client_id = client.get("client_id", "")
        client_name = client.get("client_name", "")

        applicable = get_client_applicable_compliances(client, calendar_df)

        for cal_row in applicable:
            # Parse due date
            due_date_raw = cal_row.get("due_date", "")
            due_dt = parse_due_date(
                due_date_raw,
                reference_month=today.month,
                reference_year=today.year,
            )

            if due_dt is None:
                continue

            # Filter to the relevant window
            if due_dt < window_start or due_dt > window_end:
                continue

            days_until = (due_dt - today).days

            # Assign status
            if days_until < 0:
                status = "OVERDUE"
            elif days_until == 1:
                status = "DUE_SOON_1"
            elif days_until <= 7:
                status = "DUE_SOON_7"
            else:
                status = "SAFE"

            # Penalty per day (numeric, default 0)
            try:
                penalty = float(cal_row.get("penalty_per_day", 0))
            except (ValueError, TypeError):
                penalty = 0.0

            rows.append({
                "client_id": client_id,
                "client_name": client_name,
                "compliance_type": cal_row.get("compliance_type", ""),
                "due_date": due_dt.strftime("%Y-%m-%d"),
                "days_until_due": days_until,
                "status": status,
                "penalty_per_day": penalty,
            })

    matrix_df = pd.DataFrame(rows)

    if matrix_df.empty:
        matrix_df = pd.DataFrame(columns=[
            "client_id", "client_name", "compliance_type",
            "due_date", "days_until_due", "status", "penalty_per_day"
        ])

    return matrix_df.sort_values("days_until_due").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4. validate_against_missed_log
# ---------------------------------------------------------------------------

def validate_against_missed_log(deadline_matrix_df, missed_log_df):
    """
    Cross-check the deadline matrix against the historical missed-deadlines log.

    For each of the 11 historical missed deadlines, check whether the
    (client_id, compliance_type) pair appears in the deadline matrix.
    Because the historical dates may be outside the matrix window,
    we check for matching client_id + compliance_type regardless of date.

    Args:
        deadline_matrix_df: Output of build_deadline_matrix().
        missed_log_df:      The missed_deadlines_log DataFrame (11 rows).

    Returns:
        dict with keys:
            'detected'   - number of historical misses found in the matrix
            'total'      - total historical misses (should be 11)
            'missed_ids' - list of client_ids NOT detected
            'details'    - list of dicts with match info
    """
    total = len(missed_log_df)
    detected = 0
    missed_ids = []
    details = []

    # Build a set of (client_id, compliance_type) from the matrix for fast lookup
    if not deadline_matrix_df.empty:
        matrix_pairs = set(
            zip(
                deadline_matrix_df["client_id"].astype(str),
                deadline_matrix_df["compliance_type"].astype(str),
            )
        )
    else:
        matrix_pairs = set()

    for _, row in missed_log_df.iterrows():
        cid = str(row.get("client_id", "")).strip()
        ctype = str(row.get("compliance_type", "")).strip()
        due = str(row.get("due_date", ""))

        found = (cid, ctype) in matrix_pairs

        if found:
            detected += 1
        else:
            missed_ids.append(cid)

        details.append({
            "client_id": cid,
            "compliance_type": ctype,
            "due_date": due,
            "found_in_matrix": found,
        })

    result = {
        "detected": detected,
        "total": total,
        "missed_ids": missed_ids,
        "details": details,
    }

    print(f"Validation: {detected}/{total} historical missed deadlines detected")
    if missed_ids:
        print(f"  Not detected client_ids: {missed_ids}")

    return result


# ---------------------------------------------------------------------------
# 5. get_upcoming_reminders
# ---------------------------------------------------------------------------

def get_upcoming_reminders(deadline_matrix_df):
    """
    Filter the deadline matrix to only DUE_SOON_7 or DUE_SOON_1 rows.

    Args:
        deadline_matrix_df: Output of build_deadline_matrix().

    Returns:
        DataFrame of upcoming reminders, sorted by due_date ascending.
    """
    if deadline_matrix_df.empty:
        return deadline_matrix_df

    reminders = deadline_matrix_df[
        deadline_matrix_df["status"].isin(["DUE_SOON_7", "DUE_SOON_1", "OVERDUE"])
    ].copy()

    return reminders.sort_values("due_date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# CLI test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import sys

    # Add project root to path so we can import modules
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)

    from modules import load_all_data

    print("=" * 70)
    print("  DEADLINE TRACKER - Test Run")
    print("=" * 70)

    # Load all data
    data = load_all_data()
    profiles = data.client_profiles
    cal_df = data.compliance_calendar
    missed = data.missed_deadlines

    # --- Test 1: parse_due_date ---
    print("\n--- Test 1: parse_due_date ---")
    test_cases = [
        ("21-04-2024", 4, 2024),
        ("15-02-2025", 2, 2025),
        ("15th of following month", 4, 2026),
        ("30th of following month", 1, 2026),
        ("31st of March", 3, 2026),
        ("15th June", 6, 2026),
        ("7th of same month", 4, 2026),
        ("31st of February", 2, 2026),   # edge case: should clamp to 28
    ]
    for text, ref_m, ref_y in test_cases:
        result = parse_due_date(text, ref_m, ref_y)
        print(f"  '{text}' (ref {ref_m}/{ref_y}) -> {result}")

    # --- Test 2: get_client_applicable_compliances ---
    print("\n--- Test 2: get_client_applicable_compliances ---")
    for i in [0, 4, 5]:  # sample clients
        client = profiles.iloc[i]
        applicable = get_client_applicable_compliances(client, cal_df)
        types = set(r.get("compliance_type", "") for r in applicable)
        pf = "Yes" if pd.notna(client.get("pf_reg")) and str(client.get("pf_reg")).strip() else "No"
        esic = "Yes" if pd.notna(client.get("esic_reg")) and str(client.get("esic_reg")).strip() else "No"
        print(f"  {client['client_id']} ({client.get('filing_frequency','?')}) "
              f"PF={pf} ESIC={esic} -> {len(applicable)} rows, types: {types}")

    # --- Test 3: build_deadline_matrix ---
    print("\n--- Test 3: build_deadline_matrix ---")
    matrix = build_deadline_matrix(profiles, cal_df)
    print(f"  Matrix shape: {matrix.shape}")
    if not matrix.empty:
        print(f"  Status counts:")
        for status, count in matrix["status"].value_counts().items():
            print(f"    {status}: {count}")
        print(f"\n  Sample rows (first 10):")
        print(matrix.head(10).to_string(index=False))
    else:
        print("  [INFO] Matrix is empty - calendar dates may be outside the 60-day window.")

    # --- Test 4: validate_against_missed_log ---
    print("\n--- Test 4: validate_against_missed_log ---")
    validation = validate_against_missed_log(matrix, missed)

    # --- Test 5: get_upcoming_reminders ---
    print("\n--- Test 5: get_upcoming_reminders ---")
    reminders = get_upcoming_reminders(matrix)
    print(f"  Upcoming reminders: {len(reminders)} rows")
    if not reminders.empty:
        print(reminders.head(10).to_string(index=False))

    print("\n" + "=" * 70)
    print("  All tests completed.")
    print("=" * 70)

