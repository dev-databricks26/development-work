import streamlit as st
import json
import pandas as pd
from sqlglot import parse_one, exp


class DqxUIComponents:
    def __init__(self, db_manager, dqx_h , config_catalog , config_schema):
        self.db = db_manager
        self.dqx = dqx_h
        self.config_catalog = config_catalog
        self.config_schema = config_schema
        
    def extract_column_names(self, data):
        expression = data.get('arguments', {}).get('expression', '')
        if not expression:
            return []
        try:
            parsed = parse_one(expression)
            columns = [node.name for node in parsed.find_all(exp.Column)]
            return list(dict.fromkeys(columns))
        except Exception:
            return []

    def create_bulk_configs(self, profile_checks, rule_definitions_df=None):
        bulk_configs = []
        for check in profile_checks:
            if isinstance(check, dict) and "check" in check:
                check_obj = check["check"]
                rule_func = check_obj.get('function')
                crit = check.get("criticality")
                args = check_obj.get("arguments", {})
                rid = None
                col_name = args.get("column") or args.get("columns")
                # If function is sql_expression, extract columns from expression
                if rule_func == "sql_expression":
                    cols = self.extract_column_names(check_obj)
                    col_name = cols if cols else col_name
                if rule_definitions_df is not None and rule_func:
                    rule_row = rule_definitions_df.loc[
                        rule_definitions_df['rule_function'].str.lower() == rule_func.lower()
                    ]
                    if not rule_row.empty:
                        rid = rule_row.iloc[0]['rule_id']
                bulk_configs.append({
                    "col": col_name,
                    "rid": rid,
                    "crit": crit,
                    "args": args,
                    "name": check.get("name"),
                    "user_metadata": check.get("user_metadata")
                })
        return bulk_configs


    def render_profile_rule_generator(self, cat, schema, table):
        full_table_name = f"{cat}.{schema}.{table}"
        columns_df = self.db.fetch_columns(cat, schema, table)
        all_columns = columns_df['col_name'].tolist()

        # Reset Logic -------------------------------------------------------------------------
        head_col, reset_col, spacer = st.columns([0.38, 0.12, 0.5], vertical_alignment="bottom",gap="small")
        with head_col:
            st.markdown("<h3 style='margin:0;'>Select Columns to Profile</h3>", unsafe_allow_html=True)
        with reset_col:
            if st.button("🔄Reset", key=f"reset_{full_table_name}", type="secondary", use_container_width=True):
                st.session_state[f"profile_cols_{full_table_name}"] = all_columns.copy()
                st.rerun()


        # --------------------------------------------------------------------------------------
        if f"profile_cols_{full_table_name}" not in st.session_state:
            st.session_state[f"profile_cols_{full_table_name}"] = all_columns.copy()
        profile_columns = st.session_state[f"profile_cols_{full_table_name}"]

        # Column Selection UI
        for col in profile_columns:
            row_col1, row_col2 = st.columns([4, 1])
            row_col1.text(col)
            # Fixed width via container alignment
            if row_col2.button("Delete", key=f"delete_{col}", use_container_width=True):
                profile_columns.remove(col)
                st.session_state[f"profile_cols_{full_table_name}"] = profile_columns
                st.rerun()

        selected_columns = profile_columns.copy()
        st.divider()

        # 1. & 2. BUTTON LOGIC & FIXED SIZING
        btn_col1, btn_col2, spacer_mid, dropdown_col, btn_spacer = st.columns([2, 2, 0.5, 1.5, 2])
        
        # Check if summary exists to enable/disable the Save button
        has_generated_data = f"active_profile_checks_{full_table_name}" in st.session_state
        gen_pressed = btn_col1.button("Generate Summary & Infer DQ Rules", type="primary", use_container_width=True)
        
        # Disable "Save Profile Summary" until "Generate" has been run successfully
        save_pressed = btn_col2.button(
            "Refresh Summary", 
            use_container_width=True, 
            type="secondary",
            disabled=not has_generated_data
        )

        # Dropdown for Data Percent
        with dropdown_col:
            sample_fraction_percent = st.selectbox(
                "Data %",
                options=list(range(10, 100)),
                index=99-10, # Default to 90
                key=f"sample_pct_{full_table_name}",
                label_visibility="collapsed" # Keeps UI clean next to buttons
            )
            # Optional: Add a small label above if collapsed is too bare
            st.caption("Sample %")

        # 3. Save/Refresh Logic
        if save_pressed:
            with st.spinner("Refreshing profile data..."):
                self.dqx.save_profile_data(full_table_name, all_columns, sample_fraction_percent)
                st.success(f"Profile data for {full_table_name} updated successfully!")

        # 4. Generate Logic
        if gen_pressed:
            if not selected_columns:
                st.error("Please select at least one column.")
                return

            with st.spinner("Generating profiles..."):
                res_summary_stats, res_profiles = self.dqx.load_profile_data(full_table_name, selected_columns, sample_fraction_percent)
                profile_checks = self.dqx.generate_profile_checks(res_profiles, full_table_name)

                self.db.insert_rules(self.config_catalog, self.config_schema, profile_checks)
                self.db.fetch_rule_definitions.clear(self.db, self.config_catalog, self.config_schema)
                fresh_rules_df = self.db.fetch_rule_definitions(self.config_catalog, self.config_schema)
                
                st.session_state[f"active_profile_checks_{full_table_name}"] = profile_checks
                st.session_state[f"active_summary_stats_{full_table_name}"] = res_summary_stats
                st.session_state[f"bulk_configs_{full_table_name}"] = self.create_bulk_configs(profile_checks , fresh_rules_df)
                st.rerun() # Rerun to enable the Save button immediately

        # 5. Display Logic
        if has_generated_data:
            profile_checks_key = f"active_profile_checks_{full_table_name}"
            res_summary_stats = st.session_state[f"active_summary_stats_{full_table_name}"]

            st.subheader("📊 Summary Stats")
            st.dataframe(pd.DataFrame(res_summary_stats), use_container_width=True)

            st.subheader("✅ Inferred DQ Rules")
            # st.dataframe(pd.DataFrame(st.session_state[profile_checks_key]), use_container_width=True)

            edited_profile_checks = st.data_editor(
                pd.DataFrame(st.session_state[profile_checks_key]),
                use_container_width=True,
                num_rows="dynamic", 
                key=f"editor_{full_table_name}"
            )
            # Convert edited_profile_checks DataFrame to list of dicts for create_bulk_configs
            edited_profile_checks_dicts = []
            for row in edited_profile_checks.to_dict(orient="records"):
                if isinstance(row.get("check"), str):
                    try:
                        row["check"] = eval(row["check"])
                    except Exception:
                        row["check"] = json.loads(row["check"].replace("'", '"'))
                edited_profile_checks_dicts.append(row)

            # # Update session state with edited profile checks
            # st.session_state[f"active_profile_checks_{full_table_name}"] = edited_profile_checks_dicts

            # 6. Bulk Save Rules Button Logic
            rules_saved_key = f"rules_saved_{full_table_name}"
            if rules_saved_key not in st.session_state:
                st.session_state[rules_saved_key] = False

            if st.button(
                "💾 Add DQ Rules", 
                use_container_width=True, 
                type="primary", 
                disabled=st.session_state[rules_saved_key]
            ):
                # # Use the edited dataframe values instead of the raw session state
                fresh_rules_df = self.db.fetch_rule_definitions(self.config_catalog, self.config_schema)
                bulk_configs = self.create_bulk_configs(edited_profile_checks_dicts , fresh_rules_df)
                
                with st.spinner("⏳ updating dq rules..."):
                    try:
                        self.db.reg_multiple_dq_rule(
                            src_catalog=cat,
                            config_catalog=self.config_catalog,
                            config_schema=self.config_schema,
                            src_schema=schema,
                            table=table,
                            rules_data=bulk_configs
                        )
                        st.session_state[rules_saved_key] = True
                        st.success(f"✅ Success! {len(bulk_configs)} rules saved.")
                        # st.rerun() 
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")


    def render_ai_rule_generator(self, cat, schema, table):
        st.subheader("AI-Assisted Rule Generation")
        st.info("Describe your data quality requirements in natural language (e.g., 'Ensure emails follow a valid regex').")

        columns_df = self.db.fetch_columns(cat, schema, table)
        full_table_name = f"{cat}.{schema}.{table}"
        
        # Session State Keys
        rules_key = f"active_ai_rules_{full_table_name}"
        bulk_key = f"ai_bulk_configs_{full_table_name}"

        # Slider for dynamic column width adjustment
        col_ratio = st.slider(
            "Adjust left/right column width",
            min_value=0.1, max_value=0.9, value=0.33, step=0.01,
            help="Adjust the proportion of Table Columns vs AI Rule Generation"
        )
        left_col, right_col = st.columns([col_ratio, 1 - col_ratio])

        with left_col:
            st.subheader("Table Columns")
            columns_df = columns_df.rename(columns={"col_name": "Field Name", "data_type": "Data Type"})
            st.dataframe(columns_df, use_container_width=True)

        with right_col:
            detect_col, _ = st.columns([1, 3])
            with detect_col:
                detect_pk_pressed = st.button("Detect Primary Keys(AI)", key=f"detect_pk_{full_table_name}", type="primary")
            
            primary_key_checks = None
            if detect_pk_pressed:
                with st.spinner("Detecting primary key..."):
                    try:
                        primary_key_checks = self.dqx.ai_detect_primary_key(full_table_name)
                        st.session_state[f"pk_attempts_{full_table_name}"] = primary_key_checks
                    except Exception as e:
                        st.error(f"Error detecting primary keys: {str(e)}")
            else:
                primary_key_checks = st.session_state.get(f"pk_attempts_{full_table_name}", None)
            
            if primary_key_checks is not None:
                if isinstance(primary_key_checks, dict) and 'all_attempts' in primary_key_checks:
                    attempts_data = primary_key_checks['all_attempts']
                    st.dataframe(pd.DataFrame(attempts_data), use_container_width=True)
                else:
                    st.error("No result found.")

            # User input
            user_prompt = st.text_area(
                "Define Data Quality in Simple English, Generate DQ Rules(AI)",
                placeholder="Email addresses must be valid.\nNo null values in 'age'.\nPrimary key must be unique.",
                height=150,
                key="ai_prompt_input"
            )
            gen_pressed = st.button("Generate DQ Rules", type="primary", key=f"gen_ai_rules_{full_table_name}")

            # --- PHASE 1: GENERATION
            if gen_pressed:
                if not user_prompt.strip():
                    st.warning("Please enter some requirements first.")
                else:
                    with st.spinner("AI is analyzing table context and generating dq rules..."):
                        try:
                            ai_rules = self.dqx.ai_assisted_rule_generation(
                                user_prompt=user_prompt,
                                input_table_name=full_table_name
                            )

                            # 1. Insert new rules
                            self.db.insert_rules(self.config_catalog, self.config_schema, ai_rules)
                            self.db.fetch_rule_definitions.clear(self.db, self.config_catalog, self.config_schema)
                            # # 3. Fetch fresh definitions for mapping
                            # fresh_rules_df = self.db.fetch_rule_definitions(self.config_catalog, self.config_schema)
                            # Save to session state so they persist across reruns
                            st.session_state[rules_key] = ai_rules
                            # st.session_state[bulk_key] = self.create_bulk_configs(ai_rules , fresh_rules_df)
                            st.success("DQ Rules generated successfully!")
                        except Exception as e:
                            st.error(f"Error generating AI dq rules: {str(e)}")
                            if "ENDPOINT_NOT_FOUND" in str(e):
                                st.info("Check if your LLM Model name in dqx_handler is correct.")

            # --- PHASE 2: PERSISTENT UI (Triggered if rules exist in session state) ---
            if rules_key in st.session_state:
                st.divider()
                st.subheader("Generated DQ Rules")
                
                current_rules = st.session_state[rules_key]
                # st.dataframe(pd.DataFrame(current_rules), use_container_width=True)
                edited_ai_rules = st.data_editor(
                    pd.DataFrame(current_rules),
                    use_container_width=True,
                    num_rows="dynamic", 
                    key=f"editor_{full_table_name}"
                )
                # Convert edited_profile_checks DataFrame to list of dicts for create_bulk_configs
                edited_ai_rules_dict = []
                for row in edited_ai_rules.to_dict(orient="records"):
                    if isinstance(row.get("check"), str):
                        try:
                            row["check"] = eval(row["check"])
                        except Exception:
                            row["check"] = json.loads(row["check"].replace("'", '"'))
                    edited_ai_rules_dict.append(row)

                # Update the source session state so it survives the next rerun
                st.session_state[rules_key] = edited_ai_rules_dict

                # 3. Fetch fresh definitions for mapping
                fresh_rules_df = self.db.fetch_rule_definitions(self.config_catalog, self.config_schema)    
                st.session_state[bulk_key] = self.create_bulk_configs(st.session_state[rules_key] , fresh_rules_df)

                # --- PHASE 3: SAVE TO DB ---
                if st.button("💾 Save DQ Rules", use_container_width=True, type="primary", key=f"save_btn_{full_table_name}"):
                    bulk_configs = st.session_state.get(bulk_key, [])

                    with st.spinner("⏳ Inserting AI-generated dq rules into database..."):
                        try:
                            self.db.reg_multiple_dq_rule(
                                src_catalog=cat,
                                config_catalog=self.config_catalog,
                                config_schema=self.config_schema,
                                src_schema=schema,
                                table=table,
                                rules_data=bulk_configs
                            )
                            st.success(f"✅ Success! {len(bulk_configs)} dq rules saved to database.")
                            # # Optional: Clear the state if you want the UI to reset after saving
                            # del st.session_state[rules_key]
                        except Exception as e:
                            st.error(f"❌ Error saving AI-generated rules: {str(e)}")

