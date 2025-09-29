import re
import pandas as pd

def split_df_by_uat(
    df,
    checkpoint_pattern=r"(required|not required)",  # regex for checkpoint
    mode="include",    # "include" (Behavior A) or "between" (Behavior B)
    include_before=False,  # include rows before first checkpoint as a group
    include_after=False    # include rows after last checkpoint as a group (only applies to mode="between")
):
    """
    Split df using rows where df['uat'] matches checkpoint_pattern (case-insensitive).

    mode="include": each group starts at checkpoint row and goes until next checkpoint (checkpoint row included).
    mode="between": groups are rows between consecutive checkpoint rows (checkpoint rows excluded).
    include_before: if True, include rows before first checkpoint as first group (even if no checkpoint).
    include_after: if True and mode=="between", include rows after last checkpoint as final group.

    Returns: list of DataFrames (each has reset index).
    """
    if "uat" not in df.columns:
        raise ValueError("DataFrame must contain a column named 'uat'")

    r = df.reset_index(drop=True).copy()
    mask = r["uat"].astype(str).str.contains(checkpoint_pattern, flags=re.IGNORECASE, regex=True, na=False)
    checkpoints = r.index[mask].tolist()

    # no checkpoints handling
    if not checkpoints:
        if include_before:
            return [r.copy()]
        return []

    parts = []

    if mode == "include":
        # Each part: from checkpoint_i (inclusive) to checkpoint_{i+1} (exclusive)
        for i, start in enumerate(checkpoints):
            end = checkpoints[i+1] if i+1 < len(checkpoints) else len(r)
            parts.append(r.iloc[start:end].reset_index(drop=True))
        # Optionally include rows before first checkpoint
        if include_before and checkpoints[0] > 0:
            parts.insert(0, r.iloc[:checkpoints[0]].reset_index(drop=True))
        return parts

    elif mode == "between":
        # Optionally include rows before the first checkpoint
        if include_before and checkpoints[0] > 0:
            parts.append(r.iloc[:checkpoints[0]].reset_index(drop=True))

        # slices between checkpoints (checkpoint_i + 1) .. (checkpoint_{i+1} - 1)
        for i in range(len(checkpoints)):
            start = checkpoints[i] + 1
            end = checkpoints[i+1] if i+1 < len(checkpoints) else len(r)
            parts.append(r.iloc[start:end].reset_index(drop=True))

        # Optionally include trailing rows after last checkpoint when last slice is empty
        if include_after and checkpoints[-1] < len(r) - 1:
            # If last slice already contains the trailing rows, don't duplicate.
            # The loop above already added start=last_checkpoint+1..end=len(r), so trailing rows are already added.
            # So nothing needed here. (Kept for clarity.)
            pass

        return parts

    else:
        raise ValueError("mode must be 'include' or 'between'")

# --------------------------
# Example usage with sample DF
# --------------------------
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

    print("Original DF:")
    print(df, "\n")

    # Behavior A: checkpoint included as start of group
    parts_include = split_df_by_uat(df, mode="include")
    print("=== mode='include' ===")
    for i, p in enumerate(parts_include, 1):
        print(f"\n-- Part {i} --")
        print(p)

    # Behavior B: checkpoint is delimiter (checkpoint rows excluded)
    parts_between = split_df_by_uat(df, mode="between")
    print("\n\n=== mode='between' ===")
    for i, p in enumerate(parts_between, 1):
        print(f"\n-- Between Part {i} --")
        print(p)

    # Example: include rows before first checkpoint as separate group
    parts_with_before = split_df_by_uat(df, mode="include", include_before=True)
    print("\n\n=== mode='include' with include_before=True ===")
    for i, p in enumerate(parts_with_before, 1):
        print(f"\n-- Part {i} --")
        print(p)
