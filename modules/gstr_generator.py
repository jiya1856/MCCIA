"""
GSTR Generator Module
======================
Generates GSTR-3B drafts from raw Tally CSV exports.
Handles messy exports (latin1 encoding, skipped rows, whitespace).
"""

import pandas as pd
import numpy as np
from datetime import datetime
import re

def parse_tally_csv(filepath_or_buffer):
    """
    Parses a messy Tally CSV export into a cleaned pandas DataFrame.
    
    Args:
        filepath_or_buffer: Path to the CSV file.
        
    Returns:
        tuple: (cleaned DataFrame, detected file_type string)
    """
    # Read with latin1 encoding and skip the first 4 rows
    df = pd.read_csv(filepath_or_buffer, skiprows=4, encoding='latin1')
    
    # Drop rows where all values are NaN
    df = df.dropna(how='all')
    
    # Strip whitespace from column names, convert to lowercase, replace spaces with underscores
    df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
    
    # Strip whitespace from all string values
    for col in df.select_dtypes(include=['object', 'string', 'category']).columns:
        df[col] = df[col].astype(str).str.strip()
        # Handle cases where stripping leaves empty strings or literal 'nan'
        df[col] = df[col].replace({'nan': np.nan, '': np.nan})
        
    # Auto-detect file type from column names
    cols = " ".join(df.columns).lower()
    file_type = "unknown"
    
    if "sales" in cols or "party_name" in cols:
        file_type = "sales"
    elif "purchase" in cols or "supplier" in cols:
        file_type = "purchase"
    elif "payment" in cols or ("ledger" in cols and "amount" in cols):
        file_type = "payment"
        
    return df, file_type

def compute_outward_supplies(sales_df):
    """
    Computes Section 3.1 Outward Supplies from a sales DataFrame.
    """
    if sales_df is None or sales_df.empty:
        return {}
        
    # Identify and clean the rate column
    rate_col = next((c for c in sales_df.columns if 'rate' in c), None)
    if rate_col:
        sales_df['clean_rate'] = sales_df[rate_col].astype(str).str.replace('%', '', regex=False).str.extract(r'(\d+\.?\d*)').astype(float).fillna(0.0)
    else:
        sales_df['clean_rate'] = 0.0
        
    # Identify and clean numeric tax/value columns
    for col in ['taxable_value', 'cgst', 'sgst', 'igst']:
        actual_col = next((c for c in sales_df.columns if col in c), None)
        if actual_col:
            sales_df[f'clean_{col}'] = pd.to_numeric(sales_df[actual_col], errors='coerce').fillna(0.0)
        else:
            sales_df[f'clean_{col}'] = 0.0
            
    # Group by rate
    rates = [0.0, 5.0, 12.0, 18.0, 28.0]
    rate_summary = {}
    
    for r in rates:
        subset = sales_df[sales_df['clean_rate'] == r]
        rate_summary[f'{int(r)}%'] = {
            'taxable_value': float(subset['clean_taxable_value'].sum()),
            'cgst': float(subset['clean_cgst'].sum()),
            'sgst': float(subset['clean_sgst'].sum()),
            'igst': float(subset['clean_igst'].sum())
        }
        
    total_taxable = float(sales_df['clean_taxable_value'].sum())
    total_cgst = float(sales_df['clean_cgst'].sum())
    total_sgst = float(sales_df['clean_sgst'].sum())
    total_igst = float(sales_df['clean_igst'].sum())
    
    # Simple logic for zero rated and exempted
    zero_rated_supplies = {
        'taxable_value': rate_summary.get('0%', {}).get('taxable_value', 0.0)
    }
    exempted_supplies = {
        'taxable_value': 0.0
    }
    
    return {
        'rate_wise_breakup': rate_summary,
        'zero_rated_supplies': zero_rated_supplies,
        'exempted_supplies': exempted_supplies,
        'totals': {
            'total_taxable': total_taxable,
            'total_cgst_collected': total_cgst,
            'total_sgst_collected': total_sgst,
            'total_igst_collected': total_igst
        }
    }

def compute_itc(purchase_df):
    """
    Computes Section 4 Eligible ITC from a purchase DataFrame.
    """
    if purchase_df is None or purchase_df.empty:
        return {
            'eligible_itc': {
                'itc_cgst': 0.0,
                'itc_sgst': 0.0,
                'itc_igst': 0.0
            }
        }
        
    # Clean tax columns
    for col in ['cgst', 'sgst', 'igst']:
        actual_col = next((c for c in purchase_df.columns if col in c), None)
        if actual_col:
            purchase_df[f'clean_{col}'] = pd.to_numeric(purchase_df[actual_col], errors='coerce').fillna(0.0)
        else:
            purchase_df[f'clean_{col}'] = 0.0
            
    itc_cgst = float(purchase_df['clean_cgst'].sum())
    itc_sgst = float(purchase_df['clean_sgst'].sum())
    itc_igst = float(purchase_df['clean_igst'].sum())
    
    return {
        'eligible_itc': {
            'itc_cgst': itc_cgst,
            'itc_sgst': itc_sgst,
            'itc_igst': itc_igst
        }
    }

def compute_net_tax_payable(outward_dict, itc_dict):
    """
    Computes net tax payable by subtracting ITC from outward tax liability.
    """
    outward_totals = outward_dict.get('totals', {})
    itc = itc_dict.get('eligible_itc', {})
    
    total_cgst = outward_totals.get('total_cgst_collected', 0.0)
    total_sgst = outward_totals.get('total_sgst_collected', 0.0)
    total_igst = outward_totals.get('total_igst_collected', 0.0)
    
    itc_cgst = itc.get('itc_cgst', 0.0)
    itc_sgst = itc.get('itc_sgst', 0.0)
    itc_igst = itc.get('itc_igst', 0.0)
    
    net_cgst = max(0.0, total_cgst - itc_cgst)
    net_sgst = max(0.0, total_sgst - itc_sgst)
    net_igst = max(0.0, total_igst - itc_igst)
    
    return {
        'net_cgst': net_cgst,
        'net_sgst': net_sgst,
        'net_igst': net_igst
    }

def generate_gstr3b(sales_file, purchase_file=None):
    """
    Coordinates GSTR-3B generation from Tally export files.
    """
    sales_df, s_type = parse_tally_csv(sales_file)
    
    purchase_df = None
    if purchase_file:
        purchase_df, p_type = parse_tally_csv(purchase_file)
        
    outward_dict = compute_outward_supplies(sales_df)
    itc_dict = compute_itc(purchase_df)
    
    net_payable = compute_net_tax_payable(outward_dict, itc_dict)
    
    source_rows = len(sales_df)
    if purchase_df is not None:
        source_rows += len(purchase_df)
        
    return {
        "client_gstin": "Auto-detect logic pending",
        "tax_period": "Auto-detect logic pending",
        "3.1_outward_supplies": outward_dict,
        "4_eligible_itc": itc_dict,
        "net_tax_payable": net_payable,
        "source_row_count": source_rows,
        "generated_at": datetime.now().isoformat()
    }

def gstr3b_to_dataframe(gstr3b_dict):
    """
    Flattens the nested GSTR-3B dict into a 2-column DataFrame for presentation.
    """
    rows = []
    
    rows.append({'Field': 'Client GSTIN', 'Value': gstr3b_dict.get('client_gstin')})
    rows.append({'Field': 'Tax Period', 'Value': gstr3b_dict.get('tax_period')})
    rows.append({'Field': 'Generated At', 'Value': gstr3b_dict.get('generated_at')})
    
    outward = gstr3b_dict.get('3.1_outward_supplies', {}).get('totals', {})
    rows.append({'Field': 'Total Taxable Value', 'Value': outward.get('total_taxable')})
    rows.append({'Field': 'Total CGST Collected', 'Value': outward.get('total_cgst_collected')})
    rows.append({'Field': 'Total SGST Collected', 'Value': outward.get('total_sgst_collected')})
    rows.append({'Field': 'Total IGST Collected', 'Value': outward.get('total_igst_collected')})
    
    itc = gstr3b_dict.get('4_eligible_itc', {}).get('eligible_itc', {})
    rows.append({'Field': 'Eligible ITC - CGST', 'Value': itc.get('itc_cgst')})
    rows.append({'Field': 'Eligible ITC - SGST', 'Value': itc.get('itc_sgst')})
    rows.append({'Field': 'Eligible ITC - IGST', 'Value': itc.get('itc_igst')})
    
    net = gstr3b_dict.get('net_tax_payable', {})
    rows.append({'Field': 'Net Payable - CGST', 'Value': net.get('net_cgst')})
    rows.append({'Field': 'Net Payable - SGST', 'Value': net.get('net_sgst')})
    rows.append({'Field': 'Net Payable - IGST', 'Value': net.get('net_igst')})
    
    rows.append({'Field': f'Source rows processed: {gstr3b_dict.get("source_row_count")}', 'Value': ''})
    
    return pd.DataFrame(rows)

if __name__ == "__main__":
    import os
    import sys
    
    # Setup paths for test run
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sales_path = os.path.join(project_root, "data", "client_transactions_sample", "sales_register.csv")
    purchase_path = os.path.join(project_root, "data", "client_transactions_sample", "purchase_register.csv")
    
    print("=" * 70)
    print("  GSTR-3B GENERATOR - Test Run")
    print("=" * 70)
    
    if os.path.exists(sales_path):
        result = generate_gstr3b(sales_path, purchase_path if os.path.exists(purchase_path) else None)
        df = gstr3b_to_dataframe(result)
        print("\n" + df.to_string(index=False))
        
        output_path = os.path.join(project_root, "gstr3b_output.csv")
        df.to_csv(output_path, index=False)
        print(f"\n[OK] Output saved to: {output_path}")
    else:
        print(f"[ERROR] Sample file not found at: {sales_path}")
