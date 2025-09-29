import re
import pandas as pd

def split_by_uat_checkpoints_include(df, checkpoint_pattern=r"(required|not required)"):
    """
    Split dataframe so each part STARTS at a row whose 'uat' matches checkpoint_pattern
    (case-insensitive) and includes rows up to (but not including) the next checkpoint.
    Returns a list of DataFrames (each reset_index).
    """
    if "uat" not in df.columns:
        raise ValueError("DataFrame must contain column named 'uat'")

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

# ---------------------------
# Example usage and validation
# ---------------------------
if __name__ == "__main__":
    df = pd.DataFrame({
        "admin console screen": [
            "login", "dashboard", "settings", "profile", "help",
            "billing", "reports", "users", "logout"
        ],
        "uat": [
            "", "Required: must test", "", "", "Not Required",
            "", "Required again", "", ""
        ]
    })

    parts = split_by_uat_checkpoints_include(df)

    for i, p in enumerate(parts, 1):
        print(f"\n--- Part {i} ---")
        print(p)
