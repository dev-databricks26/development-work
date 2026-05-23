import streamlit as st
import json
import pandas as pd
import time
import re


class UIComponents:
    def __init__(self, db_manager, workflow_manager, config_catalog, config_schema):
        self.db = db_manager
        self.wm = workflow_manager
        self.config_catalog = config_catalog
        self.config_schema = config_schema


    def reset_configuration_form(self):
        # 1. Clear the structural and visibility states
        st.session_state.column_rule_counts = {}
        st.session_state.hidden_columns = set()
        st.session_state.rules_to_deactivate = []

        # 2. Clear all dynamic widget keys from session_state
        keys_to_delete = [
            key for key in st.session_state.keys() 
            if any(key.startswith(prefix) for prefix in ["dim_t4_", "rule_t4_", "crit_t4_", "args_t4_"])
        ]
        for key in keys_to_delete:
            del st.session_state[key]
        
        # 3. Force a rerun to refresh the UI
        st.rerun()
        

    def render_object_overview(self, cat, schema, table):
        st.subheader("📋 Overview")
        col1, col2 = st.columns([2, 5])
        with col1:
            st.markdown("**Table Overview**")
            overview = self.db.fetch_table_definition(cat, schema, table)
            st.code(overview, language=None)
        with col2:
            st.markdown("**Column Details**")
            df = self.db.fetch_columns(cat, schema, table)
            df = df.rename(columns={"col_name": "Field Name", "data_type": "Data Type"})
            st.dataframe(df, use_container_width=True, hide_index=True)


    def render_active_dq_rules(self, cat, schema, table):
        st.subheader("🛡️ Active DQ Rules")
        
        df_mappings = self.db.fetch_dqx_mappings(
            self.config_catalog, self.config_schema, cat, schema, table
        )

        if not df_mappings.empty:
            # Clean up data for display
            display_df = df_mappings[[
                'column', 'rule_name', 'rule_description', 'arguments'
            ]].copy()
            
            # Rename columns for a polished look
            display_df.columns = ["Column", "Rule", "Description", "Parameters"]

            # Use st.dataframe for an interactive, scrollable table
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Column": st.column_config.TextColumn("Column", help="Target column for the rule"),
                    "Rule": st.column_config.TextColumn("Rule Name"),
                    "Description": st.column_config.TextColumn("Description"),
                    "Parameters": st.column_config.TextColumn("Arguments")
                }
            )
            
            st.caption(f"Showing {len(display_df)} active rules for {cat}.{schema}.{table}")
        else:
            st.info("No active DQ rules found.")
        st.divider()


    def render_add_rules_mapping(self, cat, schema, table):
        st.subheader("📝 Create/Modify Rules Manually")
        col_title, col_reset, col_refresh = st.columns([8, 2, 2])
        if col_reset.button("🔄Reset", use_container_width=True, help="Reset all inputs and column visibility"):
            self.reset_configuration_form()
        if col_refresh.button("🌀Reload", use_container_width=True, help="Clear cache and refresh panel"):
            self.db.fetch_dqx_mappings.clear(self.config_catalog, self.config_schema, cat, schema, table)
            st.rerun()
        # ---------------------------------------

        # 1. Fetch metadata needed for the form
        dims = self.db.fetch_rule_dimensions(self.config_catalog, self.config_schema)
        df_rules = self.db.fetch_rule_definitions(self.config_catalog, self.config_schema)
        df_cols = self.db.fetch_columns(cat, schema, table)

        # --- NEW: Fetch Existing Mappings for this Table ---
        df_existing = self.db.fetch_dqx_mappings(self.config_catalog, self.config_schema, cat, schema, table).reset_index(drop=True)
        df_existing = df_existing.loc[:, ~df_existing.columns.duplicated()].copy()
        df_existing.reset_index(drop=True, inplace=True)
        
        bulk_configs = []
        all_args_filled = True
        
        # Table Header
        h_cols = st.columns([2, 1.5, 2, 1.2, 2, 0.4, 0.4])
        for col_ui, label in zip(h_cols, ["**Column**", "**Dimension**", "**Rule**", "**Criticality**", "**Args (JSON)**", "**+**", "**-**"]):
            col_ui.write(label)
        st.divider()

        # 2. Render Row-by-Row Configuration
        for idx, row in df_cols.iterrows():
            col_name = row['col_name']
            if col_name in st.session_state.get('hidden_columns', set()): 
                continue
            
            # --- EXISTING RULES SECTION (Corrected Logic) ---
            if not df_existing.empty:
                col_rules = df_existing[df_existing['column'] == col_name]
                
                # Initialize session state for tracking deactivations
                deactivate_key = f"rules_to_deactivate_{col_name}"
                if deactivate_key not in st.session_state:
                    st.session_state[deactivate_key] = []

                if not col_rules.empty:
                    # Filter for active rules AND rules not currently marked for deactivation in this session
                    active_col_rules = col_rules[col_rules.get('is_active', True) == True]
                    display_rules = active_col_rules[~active_col_rules['rule_id'].astype(str).isin(st.session_state[deactivate_key])].copy()
                    display_rules.reset_index(drop=True, inplace=True)

                    with st.expander(f"📜 Existing Rules for {col_name} ({len(display_rules)})", expanded=False):
                        t_cols = st.columns([2, 2, 2, 2, 1])
                        t_cols[0].write("**Rule Name**")
                        t_cols[1].write("**Criticality**")
                        t_cols[2].write("**Arguments**")
                        t_cols[3].write("**Description**")
                        t_cols[4].write("**Action**")
                        st.divider()

                        for _, e_row in display_rules.iterrows():
                            r_id = str(e_row['rule_id'])
                            r_cols = st.columns([2, 2, 2, 2, 1])
                            r_cols[0].write(e_row['rule_name'])
                            r_cols[1].code(e_row['criticality'])
                            r_cols[2].code(e_row['arguments'])
                            r_cols[3].write(e_row['rule_description'])
                            
                            # If user clicks X, add rule_id to session state and rerun to update UI
                            if r_cols[4].button("❌", key=f"btn_deact_{col_name}_{r_id}"):
                                st.session_state[deactivate_key].append(r_id)
                                st.rerun()

                        # Action Footer
                        if st.session_state[deactivate_key]:
                            st.warning(f"⚠️ {len(st.session_state[deactivate_key])} rules marked for deactivation.")
                            b_col1, b_col2 = st.columns([1, 4])
                            
                            if b_col1.button("💾Save", key=f"save_final_{col_name}", type="primary"):
                                full_table = f"{cat}.{schema}.{table}"
                                
                                for r_id_to_del in st.session_state[deactivate_key]:
                                    self.db.deactivate_dq_rule(
                                        self.config_catalog, 
                                        self.config_schema, 
                                        full_table, 
                                        col_name, 
                                        r_id_to_del
                                    )
                                
                                # Clear session state and cache
                                st.session_state[deactivate_key] = []
                                # Important: Use your specific DB clear method
                                self.db.fetch_dqx_mappings.clear(self.db, self.config_catalog, self.config_schema, cat, schema, table)
                                st.cache_data.clear()
                                st.success("Changes saved to database!")
                                st.rerun()
                            
                            if b_col2.button("↩️Undo", key=f"undo_{col_name}"):
                                st.session_state[deactivate_key] = []
                                st.rerun()


            if col_name not in st.session_state.column_rule_counts:
                st.session_state.column_rule_counts[col_name] = 1

            for i in range(st.session_state.column_rule_counts[col_name]):
                row_key = f"t4_{col_name}_{i}_{idx}"  # Add idx to ensure uniqueness
                r_c1, r_c2, r_c3, r_c4, r_c5, r_c6, r_c7 = st.columns([2, 1.5, 2, 1.2, 2, 0.4, 0.4])
                
                # Column Name & Hide Logic
                if i == 0:
                    sub = r_c1.columns([0.3, 0.7])
                    hide_btn_key = f"hide_{col_name}_{idx}"
                    if sub[0].button("🗑️", key=hide_btn_key):
                        st.session_state.hidden_columns.add(col_name)
                        st.rerun()
                    sub[1].markdown(f"**{col_name}**")
                else:
                    r_c1.markdown(f"↳ *{col_name}*")

                # Dropdowns and Inputs
                sel_dim = r_c2.selectbox("Dim", options=["All"] + dims, label_visibility="collapsed", key=f"dim_{row_key}")
                mask = [True]*len(df_rules) if sel_dim == "All" else df_rules['rule_dimension'] == sel_dim
                
                sel_rule = r_c3.selectbox("Rule", options=["-- Skip --"] + df_rules[mask]['rule_info'].tolist(), label_visibility="collapsed", key=f"rule_{row_key}")
                crit = r_c4.selectbox("Crit", options=["error", "warn"], label_visibility="collapsed", key=f"crit_{row_key}")
                
                # Dynamic Placeholder logic
                p_val = '{"key": "value"}'
                p_req = True
                if sel_rule != "-- Skip --":
                    rid = sel_rule.split(" - ")[0].strip()
                    m = df_rules[df_rules['rule_id'].astype(str) == rid]
                    if not m.empty: 
                        p_val = m.iloc[0]['argument_placeholder']
                        p_req = m.iloc[0]['is_arg_mendatory']
                
                # Dynamic Placeholder and Example Text Autofill
                example_text = f"e.g: {p_val}"
                args = r_c5.text_input("Args", placeholder=p_val, label_visibility="collapsed", key=f"args_{row_key}")
                r_c5.caption(example_text)

                # Add/Remove Row Buttons
                if r_c6.button("➕", key=f"add_{row_key}"):
                    st.session_state.column_rule_counts[col_name] += 1
                    st.rerun()
                if st.session_state.column_rule_counts[col_name] > 1 and r_c7.button("➖", key=f"rem_{row_key}"):
                    st.session_state.column_rule_counts[col_name] -= 1
                    st.rerun()

                # Collect configuration if rule is selected
                if sel_rule != "-- Skip --":
                    is_valid_json = True
                    try:
                        if args.strip():
                            json.loads(args)
                    except ValueError:
                        is_valid_json = False

                    if not args.strip() and p_req==True:
                        r_c5.error("Required ⚠️")
                        all_args_filled = False
                    elif not is_valid_json:
                        r_c5.error("Invalid JSON ❌")
                        all_args_filled = False
                    else:
                        bulk_configs.append({
                            "col": col_name, 
                            "rid": sel_rule.split(" - ")[0].strip(), 
                            "crit": crit, 
                            "args": args if p_req else p_val
                        })

        st.divider()

        # 3. Registration Logic
        if bulk_configs:
            if not all_args_filled:
                st.warning("⚠️ Some selected rules are missing required Arguments. Please fill them to continue.")

            st.write(f"Ready to register **{len(bulk_configs)}** rules.")
            if st.button("Register Rules", type="primary", disabled=not all_args_filled):
                success_count = 0
                error_logs = []
                progress_bar = st.progress(0)
                # Using the empty string spinner as you requested
                with st.spinner("Registring rules..."):
                    total_rules = len(bulk_configs)
                    for entry in bulk_configs:
                        try:
                            # Validate JSON
                            a_dict = json.loads(entry['args']) if entry['args'].strip() else {}
                            
                            success, msg = self.db.register_dq_rule(
                                self.config_catalog, self.config_schema, cat, schema, table, 
                                entry['col'], entry['rid'], entry['crit'], a_dict
                            )
                            
                            if success:
                                success_count += 1
                            else:
                                error_logs.append(f"Error in {entry['col']}: {msg}")
                        except json.JSONDecodeError:
                            error_logs.append(f"Invalid JSON format for column: {entry['col']}")
                        except Exception as e:
                            error_logs.append(f"Unexpected error for {entry['col']}: {str(e)}")
                        
                        # Update progress bar (0.0 to 1.0)
                        progress_bar.progress((success_count + len(error_logs)) / total_rules)

                if success_count > 0:
                    self.db.fetch_dqx_mappings.clear(self.db, self.config_catalog, self.config_schema, cat, schema, table)
                    st.cache_data.clear()
                    st.session_state.show_execution_summary = True
                    st.success(f"Successfully registered {success_count} rules!")
                    time.sleep(1)
                    progress_bar.empty()
                    st.rerun()
                for err in error_logs:
                    st.error(err)
