import streamlit as st
import configparser
from databricks.connect import DatabricksSession

from utils.state_manager import StateManager
from utils.database_manager import DatabaseManager
from utils.workflow_manager import WorkflowManager
from utils.dq_checks_handler import dqx_handler
from utils.ui_components import UIComponents
from utils.dqx_ui_components import DqxUIComponents
from utils.submit_ui_components import UISubmitComponents

# --- 1. Page Configuration ---
st.set_page_config(layout="wide")

# Custom CSS to shift the title up
st.markdown("""
    <style>
        /* 1. Force the main container to hug the left edge and use full width */
        .block-container {
            padding-top: 0rem !important; /* Shipped up by reducing from 1rem to 0rem */
            padding-left: 2rem !important; 
            padding-right: 2rem !important;
            max-width: 100% !important;
            margin-left: 0px !important;
        }
        
        /* 2. Remove default Streamlit centering flexbox */
        [data-testid="stMainViewContainer"] {
            align-items: flex-start !important;
        }

        /* 3. Header management */
        [data-testid="stHeader"] {
            background: rgba(0,0,0,0);
            color: transparent;
        }

        /* 4. Shift title up and ensure left alignment */
        .stHeading h1 {
            margin-top: -45px; /* Shipped up by changing from -20px to -45px */
            padding-top: 0px;
            text-align: left;
        }

        /* 5. Object Name: Removed large left margin to keep it flush */
        .object-name-container {
            margin-top: 10px !important;
            margin-left: 0px !important; 
            margin-bottom: 20px !important;
            color: #555;
            font-size: 18px !important;
            font-weight: 500;
        }

        /* 6. Sidebar width constraints */
        [data-testid="stSidebar"] {
            min-width: 250px !important;
            max-width: 300px !important;
        }

        /* Sidebar top padding */
        [data-testid="stSidebar"] > div:first-child {
            padding-top: 1rem;
        }

        /* 7. Wizard/Progress Bar Labels */
        .wizard-label {
            height: 30px;
            display: flex;
            align-items: flex-end;
            margin-bottom: 5px;
            font-size: 14px;
            white-space: nowrap;
        }
    </style>
""", unsafe_allow_html=True)


# --- 2. Load Config & Profile ---
env = 'DEV'
config = configparser.ConfigParser()
config.read('config.conf')


# Extract variables based on selection
HOST = config.get(env, 'server_hostname')
PATH = config.get(env, 'http_path')
TOKEN = config.get(env, 'token')
JOB_ID = config.get(env, 'job_id')
config_catalog = config.get('DEFAULT', 'dqx_catalog_name')
config_schema = config.get('DEFAULT', 'dqx_config_schema')


# --- 3. Initialize Managers ---
@st.cache_resource(show_spinner='Initializing Core Services...')
def init_base_managers():
    return (
        DatabaseManager(HOST, PATH, TOKEN), 
        WorkflowManager(HOST, TOKEN, JOB_ID)
    )

def get_spark():
    return DatabricksSession.builder.serverless().getOrCreate()


try:
    db, wm = init_base_managers()
    dqx_h = dqx_handler(get_spark()) 
    ui = UIComponents(db, wm, config_catalog, config_schema)
    dqx_ui = DqxUIComponents(db, dqx_h, config_catalog, config_schema)
    ui_submit = UISubmitComponents(db, dqx_h, wm, config_catalog, config)

    StateManager.initialize()

    # --- 4. Main UI Sidebar Navigation ---
    st.markdown(
        """
        <div style="display: flex; align-items: center; margin-bottom: 0px;">
            <h1 style="margin-bottom: 0px; margin-right: 4px;">🛡️ Data Quality Accelerator</h1>
            <span style="font-size:16px; color:#666; margin-top:0px;">(Powered by DQX)</span>
        </div>
        """,
        unsafe_allow_html=True
    )

    with st.sidebar:
        if st.button("🔄 Reset", use_container_width=True):
            StateManager.reset_portal()
        st.divider()

        # Data Selectors
        catalogs = ["-- Select --"] + db.fetch_catalogs()
        cat_select = st.selectbox("Catalog", options=catalogs, key="cat_select")
        
        schemas = ["-- Select --"]
        if cat_select != "-- Select --":
            schemas += db.fetch_schemas(cat_select)
        schema_select = st.selectbox(
            "Schema", 
            options=[s for s in schemas if not (s.startswith("dqx_") or '_dqx' in s.lower())], 
            key="schema_select"
        )
        
        tables = ["-- Select --"]
        if schema_select != "-- Select --":
            tables += db.fetch_tables(cat_select, schema_select)
        prev_table = st.session_state.get("prev_table_select", "-- Select --")
        table_select = st.selectbox(
            "Table", 
            options=[t for t in tables if not (t.endswith("_output") or t.endswith("_quarantine"))], 
            key="table_select"
        )
        # Reset step if table selection changes
        if table_select != prev_table:
            st.session_state.step = 0
        st.session_state.prev_table_select = table_select

        # # Links to Databricks environment components as link text with logo
        st.divider()
        st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
        st.markdown("#### 🔗 Quick Links")
        st.markdown(
            """
            <style>
                .dqx-link {
                    text-decoration: none;
                    display: flex;
                    align-items: center;
                    font-size: 16px;
                    margin-bottom: 8px;
                    transition: text-decoration 0.2s;
                }
                .dqx-link:hover {
                    text-decoration: underline;
                }
            </style>
            <a href="https://dbc-4b58157d-c7bb.cloud.databricks.com/dashboardsv3/01f14ecddf181108b9e2252c5a21a410/published?o=7474648480850274" target="_blank" class="dqx-link">
                <span style="font-size:20px; margin-right:6px;">📊</span>
                <span style="font-size:16px;">Data Quality Dashboard</span>
            </a>
            <a href="https://dbc-4b58157d-c7bb.cloud.databricks.com/jobs/737121623984611" target="_blank" class="dqx-link">
                <span style="font-size:20px; margin-right:6px;">🚀</span>
                <span style="font-size:16px;">Data Quality Workflow</span>
            </a>
            <a href="https://databrickslabs.github.io/dqx/" target="_blank" class="dqx-link">
                <span style="font-size:20px; margin-right:6px;">📚</span>
                <span style="font-size:16px;">DQX Documentation</span>
            </a>
            """,
            unsafe_allow_html=True
        )
        # 🏷️ App Branding & Version Footer (fixed at bottom of sidebar)
        st.markdown(
            """
            <style>
                .dqx-footer {
                    position: fixed;
                    left: 0;
                    bottom: 30px;
                    width: 250px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    opacity: 0.8;
                    z-index: 100;
                }
                @media (max-width: 600px) {
                    .dqx-footer { width: 100vw; }
                }
            </style>
            <div class="dqx-footer">
                <span style="font-size: 24px;">🛡️</span>
                <span style="font-size: 14px; font-weight: 500; margin-top: 2px;">DQX Portal v1.0.1</span>
            </div>
            """, 
            unsafe_allow_html=True
        )

    # --- 5. Main Content Area ---
    if cat_select != "-- Select --" and table_select != "-- Select --":
        st.markdown(
            f'<div class="object-name-container"><b>Object Name:</b> {cat_select}.{schema_select}.{table_select}</div>', 
            unsafe_allow_html=True
        )

        # 1. Define Step Labels
        wizard_steps = [
            "🔍 Overview",
            "🛡️ Active DQ Rules", 
            "🧪 Inferred DQ Rules",
            "🤖 AI-Assisted DQ Rules",
            "🆕 Manage DQ Rules",
            "✅ Review and Submit"
        ]

        # Initialize session state for navigation
        if 'step' not in st.session_state:
            st.session_state.step = 0

        # 2. Visual Progress Bar (Non-clickable tabs)
        cols = st.columns(len(wizard_steps))
        for i, step_label in enumerate(wizard_steps):
            if i == st.session_state.step:
                label_html = f'<div class="wizard-label"><b>{step_label}</b></div>'
                line_color = "#28a745"
            elif i < st.session_state.step:
                label_html = f'<div class="wizard-label">{step_label}</div>'
                line_color = "#28a745"
            else:
                label_html = f'<div class="wizard-label" style="color:gray">{step_label}</div>'
                line_color = "#ccc"
            # Render both label and bar
            cols[i].markdown(label_html, unsafe_allow_html=True)
            cols[i].markdown(f"<hr style='border: 3px solid {line_color}; margin: 0; padding: 0;'>", unsafe_allow_html=True)



        # 3. Navigation Helper Functions
        def go_next(): st.session_state.step += 1
        def go_back(): st.session_state.step -= 1
        def skip_to_update(): st.session_state.step = 4

        # 4. Step Routing Logic
        current = st.session_state.step

        if current == 0:
            ui.render_object_overview(cat_select, schema_select, table_select)
            if st.button("Next ➡️", use_container_width=True):
                go_next()
                st.rerun()

        elif current == 1:
            ui.render_active_dq_rules(cat_select, schema_select, table_select)
            c1, c2 = st.columns(2)
            if c1.button("⬅️ Back"): go_back(); st.rerun()
            if c2.button("Next ➡️"): go_next(); st.rerun()

        elif current == 2:
            dqx_ui.render_profile_rule_generator(cat_select, schema_select, table_select)
            c21, c22, c23 = st.columns(3)
            if c21.button("⬅️ Back"): go_back(); st.rerun()
            if c22.button("Skip to Update ⏭️"): skip_to_update(); st.rerun()
            if c23.button("Next ➡️"): go_next(); st.rerun()

        elif current == 3:
            dqx_ui.render_ai_rule_generator(cat_select, schema_select, table_select)
            c31, c32, c33 = st.columns(3)
            if c31.button("⬅️ Back"): go_back(); st.rerun()
            if c32.button("Skip to Update ⏭️"): skip_to_update(); st.rerun()
            if c33.button("Next ➡️"): go_next(); st.rerun()

        elif current == 4:
            ui.render_add_rules_mapping(cat_select, schema_select, table_select)
            c41, c42 = st.columns(2)
            if c41.button("⬅️ Back"): go_back(); st.rerun()
            if c42.button("Next ➡️"): go_next(); st.rerun()
        
        elif current == 5:
            submit_status = ui_submit.render_submit(cat_select, schema_select, table_select)
            c51, _ = st.columns(2)
            if c51.button("⬅️ Back", disabled=(submit_status == 'submitted')): go_back(); st.rerun()

    else:
        # Reset step if table selection changes to keep flow consistent
        st.session_state.step = 0
        st.info("👈 Please select a Catalog, Schema, and Table from the sidebar to begin.")

except Exception as e:
    st.error(f"⚠️ A critical error occurred: {e}")
    if st.button("Restart Application"):
        st.cache_resource.clear()
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
