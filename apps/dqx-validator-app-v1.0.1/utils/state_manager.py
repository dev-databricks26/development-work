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
        # 1. Clear specific UI widget keys
        keys_to_reset = ["cat_select", "schema_select", "table_select"]
        
        # 2. Clear dynamic rule input keys (the prefix check)
        prefixes = ["dim_t4_", "rule_t4_", "crit_t4_", "args_t4_"]
        
        for key in list(st.session_state.keys()):
            if key in keys_to_reset or any(p in key for p in prefixes):
                del st.session_state[key]
        
        # 3. Reset internal logic states
        st.session_state.column_rule_counts = {}
        st.session_state.hidden_columns = set()
        st.session_state.rules_to_deactivate = []
        st.session_state.show_execution_summary = False
            
        st.cache_data.clear()
        st.rerun()