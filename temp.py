import pandas as pd
import re
from pathlib import Path

# --- Split function (Behavior A: checkpoints included) ---
def split_by_uat_checkpoints_include(df, checkpoint_pattern=r"(required|not required)"):
    """
    Split dataframe so each part STARTS at a row whose 'uat' matches checkpoint_pattern
    and goes until the next checkpoint (checkpoint row included).
    """
    if "uat" not in df.columns:
        raise ValueError("DataFrame must contain a column named 'uat'")

    r = df.reset_index(drop=True).copy()
    mask = r["uat"].astype(str).str.contains(checkpoint_pattern, flags=re.IGNORECASE, regex=True, na=False)
    starts = r.index[mask].tolist()

    if not starts:
        return []  # no checkpoints found

    parts = []
    for i, start in enumerate(starts):
        end = starts[i+1] if i+1 < len(starts) else len(r)
        parts.append(r.iloc[start:end].reset_index(drop=True))
    return parts

# --- Save function ---
def save_parts_to_excel(parts, workbook_path="uat_chunks.xlsx"):
    """
    Save list of DataFrames into a single Excel workbook, one sheet per part.
    """
    if not parts:
        print("⚠️ No checkpoints found. Nothing to save.")
        return

    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        for i, part in enumerate(parts, start=1):
            sheet_name = f"Part_{i}"
            part.to_excel(writer, sheet_name=sheet_name, index=False)

    print(f"✅ Saved {len(parts)} parts into {workbook_path}")

# --- How to use with YOUR DataFrame ---
# Example: if you already loaded your df from Excel/CSV
# df = pd.read_excel("your_file.xlsx")   # or read_csv(...)
# df should have at least columns: ["admin console screen", "uat"]

parts = split_by_uat_checkpoints_include(df)   # df is YOUR dataframe
save_parts_to_excel(parts, "uat_chunks.xlsx")
