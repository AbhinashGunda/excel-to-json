#!/usr/bin/env python3
"""
excel_to_netfx_xml.py

Convert an Excel/CSV "spec sheet" into the NetFx hierarchical XML structure.

Usage:
    python excel_to_netfx_xml.py --input sample.xlsx --output out.xml
    python excel_to_netfx_xml.py --input sample.csv --mapping name_map.csv

Options:
    --input      : path to input Excel (.xls/.xlsx) or CSV file.
    --sheet      : sheet name (for Excel). Default: first sheet.
    --output     : path to output XML file. Default: converted.xml
    --mapping    : optional CSV mapping file with two columns: "label","xml_name"
                   to map Admin console Screen text -> exact XML property name.
    --empty-threshold : drop columns with > this fraction empty (0..1). Default 0.8
    --value-priority   : comma-separated list of columns to prefer for property values.
                         Default: UAT,PROD,Field value information,Further Details
    --verbose    : print progress
"""
import argparse
import pandas as pd
import re
from xml.etree.ElementTree import Element, SubElement, tostring
import xml.dom.minidom as minidom
import sys
from pathlib import Path

# ---------------------------
# Utilities
# ---------------------------
def read_input(path: Path, sheet_name=None, verbose=False):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    if path.suffix.lower() in (".xls", ".xlsx"):
        if verbose: print(f"Reading Excel: {path} (sheet={sheet_name})")
        xl = pd.read_excel(path, sheet_name=sheet_name, dtype=str)
        # if a sheet was returned as dict (pandas 1.x when sheet_name=None), pick first
        if isinstance(xl, dict):
            df = next(iter(xl.values()))
        else:
            df = xl
    else:
        if verbose: print(f"Reading CSV: {path}")
        df = pd.read_csv(path, dtype=str)
    # normalize column names and fillna with ""
    df.columns = [(" ".join(str(c).split())).strip() for c in df.columns]
    df = df.fillna("").astype(str)
    return df

def load_mapping(map_path: Path):
    if not map_path:
        return {}
    df = pd.read_csv(map_path, dtype=str).fillna("")
    mapping = {}
    # expect columns named 'label' and 'xml_name' or first two columns
    if "label" in df.columns and "xml_name" in df.columns:
        for _, r in df.iterrows():
            mapping[str(r["label"]).strip()] = str(r["xml_name"]).strip()
    else:
        # fallback: first two columns
        cols = df.columns.tolist()
        for _, r in df.iterrows():
            mapping[str(r[cols[0]]).strip()] = str(r[cols[1]]).strip()
    return mapping

def infer_provider(title: str):
    if not isinstance(title, str):
        return "UnknownProvider"
    t = title.lower()
    if "netfx client" in t or "netfxclient" in t:
        return "NetFxClient"
    if "agg group" in t:
        return "AggGroupRules"
    if "negative profit" in t or "profit threshold" in t or "netfxprofit" in t:
        return "NetFxProfitThreshold"
    if "merchantssl" in t or "ssl" in t:
        return "MerchantsSslLinkage"
    if "get limits" in t or "getlimits" in t or "limits" in t:
        return "NetFxGetLimits"
    if "merchant" in t:
        return "NetFxMerchant"
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in title).strip("_")
    return cleaned or "UnknownProvider"

def infer_prop_name(text: str, user_map: dict):
    text = str(text or "").strip()
    if not text:
        return "unknown"
    # direct mapping override
    if text in user_map:
        return user_map[text]
    # normalize
    key = re.sub(r'(&gt;|>|\\|/)', ' ', text, flags=re.IGNORECASE)
    key = re.sub(r'[^0-9a-zA-Z ]+', ' ', key).strip()
    parts = [p for p in re.split(r'\s+', key) if p]
    if not parts:
        return "unknown"
    # try some known conversions
    known = {
        "sds": "sdsId", "sdsid": "sdsId", "merchantid": "merchantId",
        "timezone": "timezone", "endofdayaggtime": "endOfDayAggTime",
        "nettingfactor": "nettingFactor", "negprofitthreshold": "negProfitThreshold",
        "barxuserid": "barxUserId", "entityname": "entityName", "lasmodus": "lasModUsr",
        "lasmodus r": "lasModUsr"
    }
    key_join = "".join(parts).lower()
    if key_join in known:
        return known[key_join]
    # else camelCase composition
    cam = parts[0].lower() + "".join(p.capitalize() for p in parts[1:])
    cam = re.sub(r'[^0-9a-zA-Z]', '', cam)
    return cam

def choose_value_for_row(row: dict, priority: list):
    # priority: list of column names to prefer (in order)
    def is_generic(v):
        if v is None:
            return True
        s = str(v).strip().lower()
        return s == "" or s in ("required", "not required", "n/a", "na")
    for col in priority:
        if col in row and not is_generic(row.get(col, "")):
            return str(row.get(col, ""))
    # fallback: any non-empty cell
    for v in row.values():
        if str(v).strip():
            return str(v)
    return ""

# ---------------------------
# Section detection
# ---------------------------
def detect_sections(df, verbose=False):
    """
    Returns a list of (section_title, start_index, end_index) where end_index is inclusive.
    Heuristics:
      - A header row is where the first column contains '>' OR Further Details mentions 'Client definition' etc.
      - Group rows from header until next header.
    """
    col1 = df.columns[0] if len(df.columns) > 0 else None
    col2 = df.columns[1] if len(df.columns) > 1 else None
    candidates = []
    for i, row in df.iterrows():
        a = str(row[col1]).strip() if col1 else ""
        b = str(row[col2]).strip() if col2 else ""
        score = 0
        if ">" in a:
            score += 3
        if len(a.split()) <= 6 and a == a.title():
            score += 1
        if any(k in b.lower() for k in ("definition", "client definition", "section")):
            score += 2
        if b == "" and (len(a) > 0 and len(a) < 100):
            score += 1
        if score >= 2:
            candidates.append(i)
    # If no explicit candidates found, fallback to splitting by blank rows or by key phrase "Client definition"
    if not candidates:
        for i, row in df.iterrows():
            if col2 and "client definition" in str(row[col2]).lower():
                candidates.append(i)
    if not candidates:
        # fallback: use first row as a single section
        return [("Sheet", 0, len(df)-1)]
    # Build sections by candidate indices
    cand_sorted = sorted(candidates)
    sections = []
    for idx_pos, start in enumerate(cand_sorted):
        end = cand_sorted[idx_pos+1] - 1 if idx_pos+1 < len(cand_sorted) else len(df)-1
        title = str(df.iloc[start][col1])
        sections.append((title, int(start), int(end)))
    if verbose:
        print("Detected sections:")
        for t,s,e in sections:
            print(f"  {t} -> rows {s}..{e}")
    return sections

# ---------------------------
# XML build
# ---------------------------
def build_xml(df, sections, mapping, value_priority):
    root = Element("data-items")
    root.set("version", "1.0-RELEASE_27.6.10_RC3")
    col_first = df.columns[0]

    # helper to add properties from a block of rows to a given element
    def add_properties(parent_elem, row_indices):
        for ridx in row_indices:
            row = dict(df.iloc[ridx])
            pname = infer_prop_name(row.get(col_first, ""), mapping)
            pval = choose_value_for_row(row, value_priority)
            prop = SubElement(parent_elem, "property")
            prop.set("name", pname)
            prop.text = pval

    # Find NetFxClient section(s) and make single client entry (prefer first detected)
    client_sec = None
    for title,start,end in sections:
        if infer_provider(title) == "NetFxClient":
            client_sec = (title,start,end)
            break

    # Index sections by provider for easier lookup
    prov_to_sections = {}
    for title,start,end in sections:
        prov = infer_provider(title)
        prov_to_sections.setdefault(prov, []).append((title, start, end))

    # Create NetFxClient if present
    if client_sec:
        title, start, end = client_sec
        client_elem = SubElement(root, "data-row"); client_elem.set("data-provider", "NetFxClient")
        add_properties(client_elem, list(range(start, end+1)))
        # Nest AggGroupRules and NetFxProfitThreshold under client if present
        for prov in ("AggGroupRules", "NetFxProfitThreshold"):
            if prov in prov_to_sections:
                for (t,s,e) in prov_to_sections[prov]:
                    for ridx in range(s, e+1):
                        child_row = df.iloc[ridx].to_dict()
                        child_elem = SubElement(client_elem, "data-row"); child_elem.set("data-provider", prov)
                        pname = infer_prop_name(child_row.get(col_first, ""), mapping)
                        pval = choose_value_for_row(child_row, value_priority)
                        prop = SubElement(child_elem, "property"); prop.set("name", pname); prop.text = pval

    # Create merchants and nest child rows
    if "NetFxMerchant" in prov_to_sections:
        merchant_sections = prov_to_sections["NetFxMerchant"]
        # For each merchant row create a data-row
        for (title,start,end) in merchant_sections:
            for ridx in range(start, end+1):
                row = df.iloc[ridx].to_dict()
                merchant_elem = SubElement(root, "data-row"); merchant_elem.set("data-provider", "NetFxMerchant")
                # add properties for merchant row (could be multiple)
                pname = infer_prop_name(row.get(col_first, ""), mapping)
                pval = choose_value_for_row(row, value_priority)
                prop = SubElement(merchant_elem, "property"); prop.set("name", pname); prop.text = pval
                # simple heuristic to attach child sections: attach all rows from child section(s) that come after this merchant row index
                for prov in ("MerchantsSslLinkage", "NetFxGetLimits"):
                    if prov in prov_to_sections:
                        for (ctitle,cstart,cend) in prov_to_sections[prov]:
                            # attach child rows that appear after merchant row index (simple positional heuristic)
                            for cr in range(cstart, cend+1):
                                if cr >= ridx:
                                    crow = df.iloc[cr].to_dict()
                                    child_elem = SubElement(merchant_elem, "data-row"); child_elem.set("data-provider", prov)
                                    pname_c = infer_prop_name(crow.get(col_first, ""), mapping)
                                    pval_c = choose_value_for_row(crow, value_priority)
                                    child_prop = SubElement(child_elem, "property"); child_prop.set("name", pname_c); child_prop.text = pval_c

    # Add any leftover section types not handled yet as top-level data-rows
    handled = set(["NetFxClient", "AggGroupRules", "NetFxProfitThreshold", "NetFxMerchant", "MerchantsSslLinkage", "NetFxGetLimits"])
    for prov, secs in prov_to_sections.items():
        if prov in handled:
            continue
        for (title,start,end) in secs:
            for ridx in range(start, end+1):
                row = df.iloc[ridx].to_dict()
                data_row = SubElement(root, "data-row"); data_row.set("data-provider", prov)
                pname = infer_prop_name(row.get(col_first, ""), mapping)
                pval = choose_value_for_row(row, value_priority)
                prop = SubElement(data_row, "property"); prop.set("name", pname); prop.text = pval

    return root

# ---------------------------
# Main
# ---------------------------
def main():
    p = argparse.ArgumentParser(description="Convert an Excel/CSV spec sheet to NetFx XML.")
    p.add_argument("--input", "-i", required=True, help="Input Excel (.xls/.xlsx) or CSV file path.")
    p.add_argument("--sheet", "-s", default=None, help="Sheet name (Excel). Defaults to first sheet.")
    p.add_argument("--output", "-o", default="converted.xml", help="Output XML file.")
    p.add_argument("--mapping", "-m", default=None, help="Optional CSV mapping: label,xml_name")
    p.add_argument("--empty-threshold", "-e", type=float, default=0.8, help="Drop columns where >this fraction empty. 0..1 (default 0.8).")
    p.add_argument("--value-priority", "-v", default="UAT,PROD,Field value information,Further Details",
                   help="Comma-separated priority of columns to pick property value from (default: UAT,PROD,Field value information,Further Details).")
    p.add_argument("--verbose", action="store_true", help="Verbose output.")
    args = p.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    mapping_path = Path(args.mapping) if args.mapping else None
    verbose = args.verbose

    # Read input
    df = read_input(input_path, sheet_name=args.sheet, verbose=verbose)

    # Basic cleaning: trim, drop all-empty rows, drop duplicate rows
    df = df.applymap(lambda x: "" if pd.isna(x) else str(x).strip())
    df = df.loc[~(df.eq("")).all(axis=1)].copy()
    df = df.drop_duplicates().reset_index(drop=True)

    # Drop columns with too many empty values
    if args.empty_threshold is not None:
        threshold = float(args.empty_threshold)
        empty_frac = (df == "").mean()
        to_drop = [c for c, f in empty_frac.items() if f > threshold]
        if verbose and to_drop:
            print(f"Dropping columns with >{threshold*100:.0f}% empty: {to_drop}")
        df = df.drop(columns=to_drop, errors="ignore")

    # Load user mapping if provided
    mapping = load_mapping(mapping_path) if mapping_path else {}

    # Detect sections
    sections = detect_sections(df, verbose=verbose)

    # Build a simple section map (row->section) - not strictly needed but useful
    # Convert sections list -> section index ranges
    # Build XML tree
    value_priority = [c.strip() for c in args.value_priority.split(",")]
    root = build_xml(df, sections, mapping, value_priority)

    # Pretty print and save
    rough = tostring(root, "utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ")
    output_path.write_text(pretty, encoding="utf-8")
    print(f"Saved XML to {output_path}")

if __name__ == "__main__":
    main()
