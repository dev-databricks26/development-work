import streamlit as st
import json
import pandas as pd
from sqlglot import parse_one, exp


class DqxUIComponents:
    def __init__(self, db_manager, dqx_h , config):
        self.db = db_manager
        self.dqx = dqx_h
        self.config_catalog = config.get('DEFAULT', 'dqx_config_catalog')
        self.config_schema =  config.get('DEFAULT', 'dqx_config_schema')


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

        # BUTTON LOGIC & FIXED SIZING
        btn_col1, btn_col2, spacer_mid, dropdown_col, btn_spacer = st.columns([2, 2, 0.5, 1.5, 2])
        
        # Generate button: disables itself after first click to prevent duplicate runs
        has_generated_data = f"active_profile_checks_{full_table_name}" in st.session_state
        if f"gen_pressed_{full_table_name}" not in st.session_state:
            st.session_state[f"gen_pressed_{full_table_name}"] = False
        gen_pressed = btn_col1.button(
            "Generate Summary & Infer DQ Rules",
            type="primary",
            use_container_width=True,
            disabled=st.session_state[f"gen_pressed_{full_table_name}"],
            on_click=lambda: st.session_state.update({f"gen_pressed_{full_table_name}": True}),
            key=f"btn_gen_{full_table_name}"
        )
        
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
                index=99-10, # Default to 99
                key=f"sample_pct_{full_table_name}",
                label_visibility="collapsed" # Keeps UI clean next to buttons
            )
            # Optional: Add a small label above if collapsed is too bare
            st.caption("Sample %")

        # Save/Refresh Logic
        if save_pressed:
            with st.spinner("Refreshing profile data..."):
                self.dqx.save_profile_data(full_table_name, all_columns, sample_fraction_percent)
                st.session_state[f"gen_pressed_{full_table_name}"] = False
                st.success(f"Profile data for {full_table_name} updated successfully!")

        # Generate Logic
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

        # Display Logic
        if has_generated_data:
            profile_checks_key = f"active_profile_checks_{full_table_name}"
            res_summary_stats = st.session_state[f"active_summary_stats_{full_table_name}"]

            st.subheader("📊 Summary Stats")
            st.dataframe(pd.DataFrame(res_summary_stats), use_container_width=True)

            st.subheader("✅ Inferred DQ Rules")
            # Load the original DataFrame
            df_profile_checks = pd.DataFrame(st.session_state[profile_checks_key])
            # Append the select checkbox column to the far right
            df_profile_checks["select"] = True

            # Render the editor with column configuration
            edited_profile_checks = st.data_editor(
                df_profile_checks,
                use_container_width=True,
                num_rows="dynamic", 
                hide_index=True,
                key=f"editor_{full_table_name}",
                column_config={
                    "select": st.column_config.CheckboxColumn(
                        "select",
                        help="Uncheck to exclude from final output",
                        default=True,
                    )
                }
            )
    
            edited_profile_checks_dicts = []
            for row in edited_profile_checks.to_dict(orient="records"):
                if row.get("select") is True:
                    row.pop("select", None)
                    if isinstance(row.get("check"), str):
                        try:
                            row["check"] = eval(row["check"])
                        except Exception:
                            try:
                                row["check"] = json.loads(row["check"].replace("'", '"'))
                            except Exception:
                                pass
                                
                    edited_profile_checks_dicts.append(row)


            # Bulk Save Rules Button Logic
            rules_saved_key = f"rules_saved_{full_table_name}"
            success_msg_key = f"success_msg_{full_table_name}"
            
            # Initialize the state keys if it doesn't exist
            if rules_saved_key not in st.session_state:
                st.session_state[rules_saved_key] = False
            if success_msg_key not in st.session_state:
                st.session_state[success_msg_key] = None

            # Render persistent success message if it exists from a previous run
            if st.session_state[success_msg_key]:
                st.success(st.session_state[success_msg_key])

    
            # Render button with an inline lambda function to lock it instantly on click
            add_btn = st.button(
                "💾 Add DQ Rules", 
                use_container_width=True, 
                type="primary", 
                disabled=st.session_state[rules_saved_key],
                on_click=lambda: st.session_state.update({rules_saved_key: True}),
                key=f"add_btn_widget_{full_table_name}"
            )
            
            if add_btn:
                fresh_rules_df = self.db.fetch_rule_definitions(self.config_catalog, self.config_schema)
                bulk_configs = self.create_bulk_configs(edited_profile_checks_dicts, fresh_rules_df)
                
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
                        # Prepare message and keep state True
                        msg = f"✅ Success! {len(bulk_configs)} rules saved."
                        st.session_state[success_msg_key] = msg
                        st.rerun()
                    except Exception as e:
                        # Reset state on error so the user can try clicking again
                        st.session_state[rules_saved_key] = False
                        st.error(f"❌ Error: {str(e)}")
                        st.rerun()



    def render_ai_rule_generator(self, cat, schema, table):
        st.subheader("AI-Assisted Rule Generation")
        st.info("Describe your data quality requirements in natural language (e.g., 'Ensure emails follow a valid regex').")

        columns_df = self.db.fetch_columns(cat, schema, table)
        full_table_name = f"{cat}.{schema}.{table}"

        # Session State Keys
        rules_key = f"active_ai_rules_{full_table_name}"
        bulk_key = f"ai_bulk_configs_{full_table_name}"
        pk_running_key = f"pk_running_{full_table_name}"
        pk_completed_key = f"pk_completed_{full_table_name}"
        gen_running_key = f"gen_running_{full_table_name}"
        gen_completed_key = f"gen_completed_{full_table_name}"
        save_completed_key = f"save_completed_{full_table_name}"

        # Initialize Session States
        if pk_running_key not in st.session_state:
            st.session_state[pk_running_key] = False
        if pk_completed_key not in st.session_state:
            st.session_state[pk_completed_key] = False
        if gen_running_key not in st.session_state:
            st.session_state[gen_running_key] = False
        if gen_completed_key not in st.session_state:
            st.session_state[gen_completed_key] = False
        if save_completed_key not in st.session_state:
            st.session_state[save_completed_key] = False

        # Slider for dynamic column width adjustment
        col_ratio = st.slider(
            "Adjust left/right column width",
            min_value=0.1, max_value=0.9, value=0.28, step=0.01,
            help="Adjust the proportion of Table Columns vs AI Rule Generation"
        )
        left_col, right_col = st.columns([col_ratio, 1 - col_ratio])

        with left_col:
            st.subheader("Table Columns")
            st.dataframe(
                columns_df, 
                column_config={"col_name": "Field Name", "data_type": "Data Type"},
                hide_index=True
            )

        with right_col:
            detect_col, _ = st.columns([1, 3])
            with detect_col:
                # Disable if PK detection or Rule Generation is processing OR has finished running for this session
                pk_disabled = (
                    st.session_state[pk_running_key]
                    or st.session_state[pk_completed_key]
                )
                detect_pk_pressed = st.button(
                    "Detect Primary Keys(AI)", 
                    key=f"detect_pk_{full_table_name}", 
                    type="primary",
                    disabled=pk_disabled,
                    on_click=lambda: st.session_state.update({pk_running_key: True})
                )

            primary_key_checks = None
            # Handle active execution block for PK detection
            if st.session_state[pk_running_key] or st.session_state[pk_completed_key]:
                with st.spinner("Detecting primary key..."):
                    try:
                        primary_key_checks = self.dqx.ai_detect_primary_key(full_table_name)
                        st.session_state[f"pk_attempts_{full_table_name}"] = primary_key_checks
                    except Exception as e:
                        st.error(f"Error detecting primary keys: {str(e)}")
                    finally:
                        st.session_state[pk_running_key] = False
                        st.session_state[pk_completed_key] = True       
            else:
                primary_key_checks = st.session_state.get(f"pk_attempts_{full_table_name}", None)
            
            if primary_key_checks is not None:
                if isinstance(primary_key_checks, dict) and 'all_attempts' in primary_key_checks:
                    attempts_data = primary_key_checks['all_attempts']
                    st.dataframe(pd.DataFrame(attempts_data), use_container_width=True)
                else:
                    st.error("No result found.")

            # User input
            st.markdown("""
                <style>
                    /* Target the internal textarea element and allow it to size by its content */
                    [data-testid="stTextArea"] textarea {
                        field-sizing: content !important;
                        min-height: 150px !important;
                    }
                </style>
            """, unsafe_allow_html=True)

            # Render the text area without a hardcoded maximum height
            user_prompt = st.text_area(
                "Define Data Quality in Simple English, Generate DQ Rules(AI)",
                placeholder="Email addresses must be valid.\nNo null values in 'age'.\nPrimary key must be unique.",
                key="ai_prompt_input"
            )

            # Disable if PK detection is running OR if Generation already completed successfully
            gen_disabled = (
                st.session_state[pk_running_key] 
                or st.session_state[gen_running_key]
                or st.session_state[gen_completed_key]
            )
            gen_pressed = st.button(
                "Generate DQ Rules", 
                type="primary", 
                key=f"gen_ai_rules_{full_table_name}",
                disabled=gen_disabled,
                on_click=lambda: st.session_state.__setitem__(gen_running_key, True) if user_prompt.strip() else None
            )

            # --- PHASE 1: VALIDATION & RERUN TRACKING
            if gen_pressed and not user_prompt.strip():
                st.warning("Please enter some requirements first.")

            # Handle active execution block for rule generation
            if st.session_state[gen_running_key]:
                with st.spinner("AI is analyzing table context and generating dq rules..."):
                    try:
                        ai_rules = self.dqx.ai_assisted_rule_generation(
                            user_prompt=user_prompt,
                            input_table_name=full_table_name
                        )

                        # Ensure ai_rules is a list of dictionaries
                        if isinstance(ai_rules, pd.DataFrame):
                            ai_rules = ai_rules.to_dict(orient="records")

                        # Automatically inject a pre-checked boolean column to the raw rules data
                        for rule in ai_rules:
                            rule["select"] = True

                        # Insert new rules
                        self.db.insert_rules(self.config_catalog, self.config_schema, ai_rules)
                        self.db.fetch_rule_definitions.clear(self.db, self.config_catalog, self.config_schema)
                        
                        # Save to session state so they persist across reruns
                        st.session_state[rules_key] = ai_rules
                        st.session_state[gen_completed_key] = True
                        st.session_state[save_completed_key] = False 
                        st.success("DQ Rules generated successfully!")
                    except Exception as e:
                        st.error(f"Error generating AI dq rules: {str(e)}")
                        if "ENDPOINT_NOT_FOUND" in str(e):
                            st.info("Check if your LLM Model name in dqx_handler is correct.")
                    finally:
                        st.session_state[gen_running_key] = False
                        st.rerun()

            # --- PHASE 2: PERSISTENT UI (Triggered if rules exist in session state) ---
            if rules_key in st.session_state:
                st.divider()
                st.subheader("Generated DQ Rules")
                
                # 1. READ ONLY: Build the initial DataFrame from session state
                current_rules = st.session_state[rules_key]
                rules_df = pd.DataFrame(current_rules)
                
                if "select" not in rules_df.columns:
                    rules_df["select"] = True
                
                # Put select column at the very end as requested
                cols = [col for col in rules_df.columns if col != "select"] + ["select"]
                rules_df = rules_df[cols]

                is_saved = st.session_state[save_completed_key]
                editor_key = f"editor_{full_table_name}"
                
                # 2. RENDER THE EDITOR: Pass the dataframe. Streamlit keeps track of edits in st.session_state[editor_key]
                edited_ai_rules = st.data_editor(
                    rules_df,
                    use_container_width=True,
                    height=200,
                    num_rows="dynamic",
                    disabled=is_saved,
                    hide_index=True,
                    key=editor_key
                )
                
                # 3. PROCESS CHANGES SAFELY: Instead of overwriting live state on every tick,
                # construct the save payload dynamically by applying edits over the baseline data frame.
                if not is_saved:
                    active_rules_for_bulk = []
                    
                    if editor_key in st.session_state and "edited_rows" in st.session_state[editor_key]:
                        # Generate an up-to-date representation of what the user sees
                        ui_df = edited_ai_rules.copy()
                        
                        for row in ui_df.to_dict(orient="records"):
                            # If a row is checked, clean up the payload for database ingestion
                            if row.get("select") is True:
                                clean_row = row.copy()
                                clean_row.pop("select", None) # Remove UI helper column
                                
                                # Parse check string fields safely
                                if isinstance(clean_row.get("check"), str):
                                    try:
                                        clean_row["check"] = eval(clean_row["check"])
                                    except Exception:
                                        try:
                                            clean_row["check"] = json.loads(clean_row["check"].replace("'", '"'))
                                        except Exception:
                                            pass
                                active_rules_for_bulk.append(clean_row)
                    else:
                        # Fallback if no edits have occurred yet (initial load state)
                        for row in current_rules:
                            if row.get("select", True) is True:
                                clean_row = row.copy()
                                clean_row.pop("select", None)
                                active_rules_for_bulk.append(clean_row)

                    # Fetch fresh definitions and update the bulk processing schema queue
                    fresh_rules_df = self.db.fetch_rule_definitions(self.config_catalog, self.config_schema)    
                    st.session_state[bulk_key] = self.create_bulk_configs(active_rules_for_bulk, fresh_rules_df)

                # --- PHASE 3: SAVE TO DB ---
                save_disabled = is_saved or st.session_state[save_completed_key]
                # --- PHASE 3: SAVE TO DB ---
                if st.button(
                    "💾 Save DQ Rules", 
                    use_container_width=True, 
                    type="primary", 
                    key=f"save_btn_{full_table_name}",
                    disabled=save_disabled,
                    on_click=lambda: st.session_state.__setitem__(save_completed_key, True)
                ):
                    bulk_configs = st.session_state.get(bulk_key, [])

                    if not bulk_configs:
                        st.warning("⚠️ No active rules selected. Please check at least one box before saving.")
                    else:
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
                                # st.session_state[save_completed_key] = True
                            except Exception as e:
                                st.error(f"❌ Error saving AI-generated rules: {str(e)}")



