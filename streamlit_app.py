"""
Validation-round annotation tool (ARR revision) — Streamlit Cloud deployment.

Blinded phrase-level judgment of explanation quality. The unblinded manifest is
NOT part of this repo; annotators see only blinded ids, sentences, predicted
emotions, and phrase-SHAP charts.

Saving: Google Sheet "SHAP_Annotations", worksheet "validation_annotations",
credentials from Streamlit secrets [gcp_service_account]. A per-session CSV
backup is kept in memory and offered as a download in the sidebar.
"""
import csv
import io
import json
from datetime import datetime
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
SHEET_NAME = "SHAP_Annotations"
WORKSHEET = "validation_annotations"

CATEGORIES = ["Correct Reason", "Wrong Reason", "Unclear / Cannot Decide"]
ANNOTATORS = {"A": "Benni", "B": "Mahdi"}
HEADER = ["blind_id", "annotator", "label", "comment", "timestamp"]


@st.cache_resource
def get_worksheet():
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)
    sh = gc.open(SHEET_NAME)
    try:
        ws = sh.worksheet(WORKSHEET)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET, rows=3000, cols=8)
        ws.append_row(HEADER)
    return ws


@st.cache_data
def load_tasks(key):
    with open(HERE / "data" / f"tasks_{key}.json") as f:
        return json.load(f)


@st.cache_data(ttl=60)
def load_done_from_sheet(annotator):
    """blind_id -> label for this annotator, from the sheet (resume support)."""
    try:
        ws = get_worksheet()
        done = {}
        for r in ws.get_all_records():
            if str(r.get("annotator")) == annotator:
                done[str(r.get("blind_id"))] = r
        return done
    except Exception as e:
        st.sidebar.error(f"Could not read progress from the sheet: {e}")
        return {}


def save(annotator, blind_id, label, comment):
    row = [blind_id, annotator, label, comment,
           datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    ws = get_worksheet()
    ws.append_row(row)
    st.session_state.setdefault("local_rows", []).append(row)
    # corrections append a new row; the LAST row per (annotator, blind_id) counts
    st.session_state.setdefault("done_session", {})[blind_id] = {
        "label": label, "comment": comment}


def main():
    st.set_page_config(page_title="Validation Round", layout="wide")
    st.sidebar.title("Validation round")
    key = st.sidebar.radio("Who are you?", list(ANNOTATORS),
                           format_func=lambda k: f"Annotator {k} ({ANNOTATORS[k]})")
    annotator = ANNOTATORS[key]
    tasks = load_tasks(key)
    done = dict(load_done_from_sheet(annotator))
    for bid, row in st.session_state.get("done_session", {}).items():
        done[bid] = row
    n_done = sum(1 for t in tasks if t["blind_id"] in done)

    st.sidebar.markdown(f"**Progress: {n_done} / {len(tasks)}**")
    st.sidebar.progress(n_done / max(len(tasks), 1))

    if st.session_state.get("local_rows"):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(HEADER)
        w.writerows(st.session_state["local_rows"])
        st.sidebar.download_button("Download this session's backup CSV",
                                   buf.getvalue(),
                                   file_name=f"{annotator}_validation_backup.csv")

    # ---- position-based navigation ----
    pos_key = f"pos_{key}"
    first_open = next((i for i, t in enumerate(tasks) if t["blind_id"] not in done),
                      len(tasks) - 1)
    if pos_key not in st.session_state:
        st.session_state[pos_key] = first_open
    pos = max(0, min(st.session_state[pos_key], len(tasks) - 1))

    c1, c2, c3, c4 = st.columns([1, 1, 2, 3])
    if c1.button("← Previous", disabled=pos == 0):
        st.session_state[pos_key] = pos - 1
        st.rerun()
    if c2.button("Next →", disabled=pos >= len(tasks) - 1):
        st.session_state[pos_key] = pos + 1
        st.rerun()
    if c3.button("Jump to next unannotated"):
        st.session_state[pos_key] = first_open
        st.rerun()
    jump = c4.selectbox("Go to sample", [t["blind_id"] +
                        ("  ✓" if t["blind_id"] in done else "")
                        for t in tasks], index=pos, label_visibility="collapsed")
    jump_idx = [t["blind_id"] for t in tasks].index(jump.split()[0])
    if jump_idx != pos:
        st.session_state[pos_key] = jump_idx
        st.rerun()

    t = tasks[pos]
    prev = done.get(t["blind_id"])
    prev_label = prev.get("label") if isinstance(prev, dict) else None
    prev_comment = str(prev.get("comment", "")) if isinstance(prev, dict) else ""

    status = " — already annotated (saving again OVERWRITES your judgment)" if prev else ""
    st.subheader(f"Sample {t['blind_id']}  ({pos + 1} of {len(tasks)}){status}")
    st.markdown(f"> {t['sentence']}")
    st.markdown(f"**Predicted emotion:** `{t['predicted_emotion']}` "
                f"(confidence {t['confidence']:.1%})")
    st.image(str(HERE / t["image"]), width=850)
    st.markdown("**Do the highlighted phrases genuinely explain why this sentence "
                "expresses the predicted emotion?**")
    idx = CATEGORIES.index(prev_label) if prev_label in CATEGORIES else None
    label = st.radio("Judgment", CATEGORIES, index=idx, key=f"lab_{key}_{t['blind_id']}")
    comment = st.text_input("Comment (optional)", value=prev_comment,
                            key=f"com_{key}_{t['blind_id']}")
    btn = "Update and next" if prev else "Save and next"
    if st.button(btn, type="primary", disabled=label is None):
        with st.spinner("Saving..."):
            save(annotator, t["blind_id"], label, comment)
        load_done_from_sheet.clear()
        remaining = [i for i, x in enumerate(tasks)
                     if x["blind_id"] not in done and x["blind_id"] != t["blind_id"]]
        nxt = next((i for i in remaining if i > pos), remaining[0] if remaining else pos)
        st.session_state[pos_key] = nxt
        st.rerun()


if __name__ == "__main__":
    main()
