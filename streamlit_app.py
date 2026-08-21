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
    st.session_state.setdefault("done_session", set()).add(blind_id)


def main():
    st.set_page_config(page_title="Validation Round", layout="wide")
    st.sidebar.title("Validation round")
    key = st.sidebar.radio("Who are you?", list(ANNOTATORS),
                           format_func=lambda k: f"Annotator {k} ({ANNOTATORS[k]})")
    annotator = ANNOTATORS[key]
    tasks = load_tasks(key)
    done = dict(load_done_from_sheet(annotator))
    for bid in st.session_state.get("done_session", set()):
        done.setdefault(bid, True)
    todo = [t for t in tasks if t["blind_id"] not in done]

    st.sidebar.markdown(f"**Progress: {len(tasks) - len(todo)} / {len(tasks)}**")
    st.sidebar.progress((len(tasks) - len(todo)) / max(len(tasks), 1))

    if st.session_state.get("local_rows"):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(HEADER)
        w.writerows(st.session_state["local_rows"])
        st.sidebar.download_button("Download this session's backup CSV",
                                   buf.getvalue(),
                                   file_name=f"{annotator}_validation_backup.csv")

    if not todo:
        st.success("All tasks done. Thank you!")
        return

    t = todo[0]
    st.subheader(f"Sample {t['blind_id']}  ({len(tasks) - len(todo) + 1} of {len(tasks)})")
    st.markdown(f"> {t['sentence']}")
    st.markdown(f"**Predicted emotion:** `{t['predicted_emotion']}` "
                f"(confidence {t['confidence']:.1%})")
    st.image(str(HERE / t["image"]), width=850)
    st.markdown("**Do the highlighted phrases genuinely explain why this sentence "
                "expresses the predicted emotion?**")
    label = st.radio("Judgment", CATEGORIES, index=None, key=f"lab_{t['blind_id']}")
    comment = st.text_input("Comment (optional)", key=f"com_{t['blind_id']}")
    if st.button("Save and next", type="primary", disabled=label is None):
        with st.spinner("Saving..."):
            save(annotator, t["blind_id"], label, comment)
        load_done_from_sheet.clear()
        st.rerun()


if __name__ == "__main__":
    main()
