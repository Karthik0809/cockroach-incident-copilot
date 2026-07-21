"""Demo UI. Deploy on ECS Fargate (or Streamlit Community Cloud) and use the
public URL as the hackathon's 'functional demo app' link.

    streamlit run app/streamlit_app.py
"""

import pathlib
import sys

import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import agent, memory  # noqa: E402

st.set_page_config(page_title="Incident Copilot", page_icon="🪳", layout="wide")

st.title("🪳 Incident Copilot")
st.caption(
    "An on-call agent whose memory lives in CockroachDB. "
    "Every incident it handles makes the next one faster."
)

with st.sidebar:
    st.subheader("Memory")
    try:
        counts = memory.stats()
        st.metric("Incidents remembered", counts["incidents"])
        st.metric("Lessons learned", counts["lessons"])
        st.metric("Sessions handled", counts["sessions"])
        st.metric("Memory recalls", counts["recalls"])
    except Exception as exc:
        st.error(f"Cannot reach memory: {exc}")

    st.divider()
    st.caption(
        "Vectors and operational rows are in the same cluster, so a resolution "
        "and its embedding commit together. No drift, no separate vector store."
    )

tab_agent, tab_search, tab_replay = st.tabs(
    ["Handle an alert", "Search memory", "Replay a session"]
)

with tab_agent:
    alert = st.text_area(
        "Paste an alert",
        height=160,
        placeholder=(
            "SEV1: orders-api p99 latency 200ms -> 25s over 15 minutes. "
            "CPU flat. Database CPU normal."
        ),
    )
    service = st.text_input("Service (optional)")

    if st.button("Run agent", type="primary") and alert.strip():
        with st.spinner("Recalling, reasoning, writing back..."):
            result = agent.handle_alert(alert, service or None)

        st.success("Done")
        st.markdown(result["answer"])

        with st.expander("Tools called"):
            for name in result["tools_used"]:
                st.write(f"- `{name}`")
        st.code(result["session_id"], language="text")
        st.caption("Session id -- paste it into the Replay tab.")

with tab_search:
    query = st.text_input("Describe a symptom")
    if query.strip():
        hits = memory.recall_incidents(query, k=6)
        if not hits:
            st.info("Nothing in memory is close enough to this.")
        for hit in hits:
            with st.container(border=True):
                st.markdown(f"**{hit.title}** — `{hit.service}` · {hit.severity}")
                st.progress(
                    min(max(hit.similarity, 0.0), 1.0),
                    text=f"similarity {hit.similarity:.2f}",
                )
                st.write(f"**Symptoms:** {hit.symptoms}")
                if hit.root_cause:
                    st.write(f"**Root cause:** {hit.root_cause}")
                if hit.resolution:
                    st.write(f"**Resolution:** {hit.resolution}")

with tab_replay:
    session_id = st.text_input("Session id")
    if session_id.strip():
        found = memory.get_session(session_id.strip())
        if not found:
            st.warning("No such session.")
        else:
            st.write(f"**Alert:** {found['alert_text']}")
            st.write(f"**Status:** {found['status']}")
            for step in found["steps"]:
                with st.chat_message("assistant" if step["role"] != "user" else "user"):
                    st.caption(f"step {step['step_no']} · {step['role']}")
                    st.write(step["content"])

            st.divider()
            st.subheader("Was the recall any good?")
            st.caption(
                "This is the loop. Marking a memory helpful raises its "
                "confidence; marking it unhelpful lowers it, and it sinks in "
                "future retrievals."
            )

            recalls = memory.session_recalls(session_id.strip())
            if not recalls:
                st.info("No memories fired during this session.")

            for rec in recalls:
                label = rec["lesson_statement"] or rec["incident_title"] or "(deleted)"
                cols = st.columns([6, 1, 1])
                with cols[0]:
                    st.write(f"{label}")
                    st.caption(f"similarity {rec['similarity']:.2f}")
                with cols[1]:
                    if st.button("👍", key=f"up-{rec['id']}"):
                        memory.mark_recall_helpful(str(rec["id"]), True)
                        st.rerun()
                with cols[2]:
                    if st.button("👎", key=f"down-{rec['id']}"):
                        memory.mark_recall_helpful(str(rec["id"]), False)
                        st.rerun()
                if rec["was_helpful"] is not None:
                    st.caption(
                        "marked helpful" if rec["was_helpful"] else "marked unhelpful"
                    )
