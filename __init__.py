"""
Mehta & Associates - Compliance Management System
===================================================
Modules package for the compliance management application.

This package contains:
- data_loader: Functions to load all data files (CSV, JSON)
- deadline_tracker: Deadline monitoring and alert generation
- qa_engine: AI-powered Q&A engine using Anthropic Claude
- gstr_generator: GSTR report generation utilities
- reminder_log: Reminder and notification logging
"""

import os
import json
import pandas as pd
from collections import namedtuple

# Define the base data directory relative to the project root
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Named tuple to hold all loaded datasets
ComplianceData = namedtuple("ComplianceData", [
    "client_profiles",
    "compliance_calendar",
    "compliance_qa",
    "gst_circulars",
    "missed_deadlines"
])


def load_all_data() -> ComplianceData:
    """
    Load all data files required by the compliance management system.

    Loads:
    - client_profiles.csv -> pandas DataFrame (stripped column names)
    - compliance_calendar_master.csv -> pandas DataFrame (stripped column names)
    - missed_deadlines_log.csv -> pandas DataFrame
    - gst_circulars_index.json -> Python dict
    - compliance_qa_dataset.csv -> pandas DataFrame

    Returns:
        ComplianceData: A named tuple containing all 5 datasets.

    Raises:
        FileNotFoundError: If any data file is missing.
        ValueError: If a CSV file cannot be parsed.
    """

    print("=" * 60)
    print("  Mehta & Associates - Loading Compliance Data")
    print("=" * 60)

    # --- 1. Load client_profiles.csv ---
    client_profiles_path = os.path.join(DATA_DIR, "client_profiles.csv")
    print(f"\n[LOAD] Loading client_profiles.csv from: {client_profiles_path}")
    client_profiles = pd.read_csv(client_profiles_path)
    client_profiles.columns = client_profiles.columns.str.strip()
    print(f"   [OK] client_profiles loaded | Shape: {client_profiles.shape}")

    # --- 2. Load compliance_calendar_master.csv ---
    compliance_calendar_path = os.path.join(DATA_DIR, "compliance_calendar_master.csv")
    print(f"\n[LOAD] Loading compliance_calendar_master.csv from: {compliance_calendar_path}")
    compliance_calendar = pd.read_csv(compliance_calendar_path)
    compliance_calendar.columns = compliance_calendar.columns.str.strip()
    print(f"   [OK] compliance_calendar loaded | Shape: {compliance_calendar.shape}")

    # --- 3. Load missed_deadlines_log.csv ---
    missed_deadlines_path = os.path.join(DATA_DIR, "missed_deadlines_log.csv")
    print(f"\n[LOAD] Loading missed_deadlines_log.csv from: {missed_deadlines_path}")
    missed_deadlines = pd.read_csv(missed_deadlines_path)
    missed_deadlines.columns = missed_deadlines.columns.str.strip()
    print(f"   [OK] missed_deadlines loaded | Shape: {missed_deadlines.shape}")

    # --- 4. Load gst_circulars_index.json ---
    gst_circulars_path = os.path.join(DATA_DIR, "gst_circulars_index.json")
    print(f"\n[LOAD] Loading gst_circulars_index.json from: {gst_circulars_path}")
    with open(gst_circulars_path, "r", encoding="utf-8") as f:
        gst_circulars = json.load(f)
    # Handle both list and dict JSON structures
    if isinstance(gst_circulars, list):
        num_circulars = len(gst_circulars)
    else:
        num_circulars = len(gst_circulars.get("circulars", []))
    print(f"   [OK] gst_circulars loaded | Entries: {num_circulars}")

    # --- 5. Load compliance_qa_dataset.csv ---
    compliance_qa_path = os.path.join(DATA_DIR, "compliance_qa_dataset.csv")
    print(f"\n[LOAD] Loading compliance_qa_dataset.csv from: {compliance_qa_path}")
    try:
        compliance_qa = pd.read_csv(compliance_qa_path)
    except UnicodeDecodeError:
        compliance_qa = pd.read_csv(compliance_qa_path, encoding="cp1252")
    compliance_qa.columns = compliance_qa.columns.str.strip()
    print(f"   [OK] compliance_qa loaded | Shape: {compliance_qa.shape}")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("  Data Loading Summary")
    print("=" * 60)
    print(f"  {'Dataset':<35} {'Rows':>6} {'Cols':>6}")
    print(f"  {'-' * 35} {'-' * 6} {'-' * 6}")
    print(f"  {'Client Profiles':<35} {client_profiles.shape[0]:>6} {client_profiles.shape[1]:>6}")
    print(f"  {'Compliance Calendar':<35} {compliance_calendar.shape[0]:>6} {compliance_calendar.shape[1]:>6}")
    print(f"  {'Missed Deadlines Log':<35} {missed_deadlines.shape[0]:>6} {missed_deadlines.shape[1]:>6}")
    print(f"  {'GST Circulars (JSON)':<35} {num_circulars:>6} {'N/A':>6}")
    print(f"  {'Compliance Q&A Dataset':<35} {compliance_qa.shape[0]:>6} {compliance_qa.shape[1]:>6}")
    print("=" * 60)
    print("  [OK] All data files loaded successfully!\n")

    return ComplianceData(
        client_profiles=client_profiles,
        compliance_calendar=compliance_calendar,
        compliance_qa=compliance_qa,
        gst_circulars=gst_circulars,
        missed_deadlines=missed_deadlines
    )


# Quick test when run directly
if __name__ == "__main__":
    data = load_all_data()
    print("\nSample client_profiles columns:", list(data.client_profiles.columns))
    print("Sample compliance_calendar columns:", list(data.compliance_calendar.columns))
