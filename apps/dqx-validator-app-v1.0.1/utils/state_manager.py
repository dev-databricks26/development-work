import streamlit as st

class StateManager:
    @staticmethod
    def initialize():
        if "active_tab" not in st.session_state:
            st.session_state.active_tab = "📋 Table Overview"
        if "column_rule_counts" not in st.session_state:
            st.session_state.column_rule_counts = {}
        if "rules_to_deactivate" not in st.session_state:
            st.session_state.rules_to_deactivate = []
        if "hidden_columns" not in st.session_state:
            st.session_state.hidden_columns = set()
        if "show_execution_summary" not in st.session_state:
            st.session_state.show_execution_summary = False

    @staticmethod
    def reset_portal():
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
