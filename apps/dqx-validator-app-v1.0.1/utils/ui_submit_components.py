import streamlit as st
import json
import yaml
import pandas as pd
import time
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication


class UISubmitComponents:
    def __init__(self, db_manager, dqx_h , workflow_manager, config):
        self.db = db_manager
        self.wm = workflow_manager
        self.dqx = dqx_h
        self.config = config
        self.config_catalog = self.config.get('DEFAULT', 'dqx_config_catalog')
        self.config_schema =  self.config.get('DEFAULT', 'dqx_config_schema')
    
    
    def get_logged_in_user_email(self, default_email):
        """Extracts the logged-in user's email from Databricks App headers."""
        # Databricks Apps use lower-case headers behind the proxy
        headers = st.context.headers
        user_email = (
            headers.get("x-forwarded-email") 
            or headers.get("x-user-email") 
            or headers.get("X-Forwarded-Email") 
            or headers.get("X-User-Email")
        )
        if not user_email:
            user_email = default_email
        return user_email


    def convert_df_to_csv_attachment(self, df: pd.DataFrame, filename: str) -> MIMEApplication:
        """
        Converts a pandas DataFrame into an in-memory CSV MIME attachment.
        """
        # Convert dataframe to CSV string without saving to disk
        csv_data = df.to_csv(index=False)
        
        # Create the attachment object
        attachment = MIMEApplication(csv_data, _subtype="csv")
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=filename
        )
        return attachment


    def send_email(self, default_email, run_id, run_url, table_name, df: pd.DataFrame):
        smtp_server = self.config.get('EMAIL', 'smtp_server')
        smtp_port = self.config.get('EMAIL', 'smtp_port')
        sender_email = self.config.get('EMAIL', 'address')
        sender_password = self.config.get('EMAIL', 'password')
        cc_email = self.config.get('EMAIL', 'copy_to')
        cc_email_list = [c.strip() for c in cc_email.split(',')]
        
        # Automatically identify the logged-in user
        recipient_email = self.get_logged_in_user_email(default_email)
        print("recipient_email ==> ", recipient_email)

        subject = f"DQX Check Triggered for Table | {table_name}"
        # --- Dynamic Rows Generation for the Box ---
        run_details = {
            "Workspace": f"{self.config.get('WORKSPACE', 'workspace_url')}",
            "Job": f"DQX_Run_Checks [{self.config.get('WORKSPACE', 'job_id')}]",
            "Job Run": run_id,
            "Status": "Triggered"
        }
        table_rows = ""
        for key, value in run_details.items():
            table_rows += f"""
            <tr>
                <td style='padding: 8px 0; font-weight: bold; color: #5f6368; width: 30%;'>{key}</td>
                <td style='padding: 8px 0; color: #202124;'>{value}</td>
            </tr>
            """

        # --- HTML Body Construction ---
        status_color = "#007bff"
        message = "DQX Execution Started"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            
            <!-- Header Section -->
            <h2 style="color: {status_color}; font-size: 24px; margin-bottom: 5px;">
                {message}
            </h2>
            <h3 style="font-size: 20px; color: #202124; margin-top: 0; margin-bottom: 20px;">
                Run details:
            </h3>
            
            <!-- Square Box Container -->
            <div style="border: 2px solid #dadce0; border-radius: 8px; padding: 20px; max-width: 600px; background-color: #f8f9fa;">
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                    <tbody>
                        <tr>
                            <td style='padding: 8px 0; font-weight: bold; color: #5f6368; width: 30%;'>Table Target</td>
                            <td style='padding: 8px 0; color: #202124; font-weight: bold;'>{table_name}</td>
                        </tr>
                        {table_rows}
                    </tbody>
                </table>
            </div>
            <p style="font-size: 0.8em; color: #666;">This is an automated notification from the DQX UI.</p>
            <p><a href="{run_url}" style="display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">View Databricks Run</a></p>
        </body>
        </html>
        """

        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Cc'] = ','.join(cc_email_list)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        # --- CSV Attachment Logic using Helper Function ---
        try:
            csv_filename = f"{table_name}_dqx_report.csv"
            attachment = self.convert_df_to_csv_attachment(df, csv_filename)
            msg.attach(attachment)
        except Exception as csv_err:
            print(f"Error generating CSV attachment: {csv_err}")

        # Combine recipients into a unique list of strings for SMTP transmission
        to_addrs = list(set([recipient_email] + cc_email_list))
        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg, to_addrs=to_addrs)
            return True, recipient_email, "Email sent successfully"
        except Exception as e:
            st.error(f"Failed to send email: {e}")
            return False, str(e)


    def generate_cron_expression(self, freq, hour, minute, days_of_week=None, day_of_month=None):
        """Generates a Databricks-compatible Quartz CRON expression."""
        # Seconds is always 0
        sec = "0"
        if freq == "Day":
            return f"{sec} {minute} {hour} * * ?"
        
        elif freq == "Week":
            if not days_of_week:
                return None
            # Map full day names to Quartz 3-letter abbreviations
            day_map = {"Sunday": "SUN", "Monday": "MON", "Tuesday": "TUE", 
                       "Wednesday": "WED", "Thursday": "THU", "Friday": "FRI", "Saturday": "SAT"}
            cron_days = ",".join([day_map[d] for d in days_of_week])
            return f"{sec} {minute} {hour} ? * {cron_days}"
        
        elif freq == "Month":
            if not day_of_month:
                return None
            return f"{sec} {minute} {hour} {day_of_month} * ?"
        return None


    def render_cron_scheduler(self):
        """Renders functional input widgets for scheduling and returns a CRON string."""
        st.markdown("---")
        st.write("📅 **Schedule Settings**")
        
        # 1. Frequency Selection
        frequency = st.selectbox("Frequency", ["Day", "Week", "Month"])
        
        # Shared columns for Time Input
        col1, col2 = st.columns(2)
        with col1:
            hour = st.selectbox("Hour (24h)", [f"{i:02d}" for i in range(24)], index=0)
        with col2:
            minute = st.selectbox("Minute", [f"{i:02d}" for i in range(0, 60, 1)], index=0) # 1-min intervals for ease

        # 2. Conditional Parameter Sub-Widgets
        days_of_week = None
        day_of_month = None

        if frequency == "Week":
            days_of_week = st.multiselect(
                "Select Days of Week", 
                ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                default=["Monday"]
            )
            if not days_of_week:
                st.warning("⚠️ Please select at least one day of the week.")
                
        elif frequency == "Month":
            day_of_month = st.selectbox(
                "Day of the Month", 
                [str(i) for i in range(1, 32)] + ["L"] # 'L' stands for last day of the month in Quartz CRON
            )

        # 3. Compute and pass expression back
        return self.generate_cron_expression(frequency, hour, minute, days_of_week, day_of_month)


    def render_submit(self, cat, schema, table):
        st.divider()
        st.subheader("🏁 Final Review & Execution")

        # Initialize variables to ensure they exist even if DB call fails
        rules_list = []
        has_rules = False

        # Fetch current mappings from DB
        dqx_mapped_df = self.db.fetch_dqx_mappings(self.config_catalog, self.config_schema, cat, schema, table)\
            [["column", "rule_name", "rule_function", "criticality", "arguments"]]
        st.dataframe(dqx_mapped_df)

        if isinstance(dqx_mapped_df, pd.DataFrame) and not dqx_mapped_df.empty:
            has_rules = True
            for _, row in dqx_mapped_df.iterrows():
                # Parse arguments safely
                raw_args = row.get('arguments', {})
                if isinstance(raw_args, list):
                    args = dict(raw_args)
                else:
                    args = raw_args
                check_dict = {
                    "criticality": row.get('criticality'),
                    "check": {
                        "function": row.get('rule_function'),
                        "arguments": {
                            k: (True if str(v).upper() == 'TRUE' 
                                else False if str(v).upper() == 'FALSE' 
                                else v) for k, v in args.items()
                        }
                    }
                }
                rules_list.append(check_dict)
        else:
            st.warning("No active rules found for this table.")

        # Export Section ================================================================================= #
        st.markdown("### 📤 Export DQ Rules")
        exp_col1, exp_col2 = st.columns(2)
        
        with exp_col1:
            st.download_button(
                label="JSON Export",
                data=json.dumps(rules_list, indent=2, default=self.dqx.json_serial),
                file_name=f"dqx_{table}_config.json",
                mime="application/json",
                disabled=not has_rules
            )

        with exp_col2:
            st.download_button(
                label="YAML Export",
                data=yaml.dump(rules_list, sort_keys=False),
                file_name=f"dqx_{table}_config.yaml",
                mime="text/yaml",
                disabled=not has_rules
            )

        
        # Execution Section ================================================================================= #
        st.subheader("🚀 Execution")

        # Initialize session state tracking keys
        if "run_now_active" not in st.session_state:
            st.session_state.run_now_active = True
        if "schedule_active" not in st.session_state:
            st.session_state.schedule_active = False

        # Create two columns for clean layout alignment
        col_run, col_sched = st.columns(2)

        with col_run:
            # Disabled automatically if Schedule Job is checked
            run_now_checked = st.checkbox(
                "Run Now", 
                value=st.session_state.run_now_active,
                disabled=st.session_state.schedule_active,
                key="run_now_cb"
            )

        with col_sched:
            # Disabled automatically if Run Now is checked
            schedule_checked = st.checkbox(
                "Schedule Job", 
                value=st.session_state.schedule_active,
                disabled=st.session_state.run_now_cb,
                key="schedule_cb"
            )

        # Sync internal execution state variables
        job_type_selection = "Run Now" if run_now_checked else "Schedule Job"
        job_type = job_type_selection.upper()
        cron_expression = None
        timezone_id = "UTC"

        # Dynamically render and manage scheduling parameters if schedule is active
        if schedule_checked:
            cron_expression = self.render_cron_scheduler()
            if cron_expression:
                st.caption(f"🎯 **Generated CRON Expression:** `{cron_expression}`")
            button_disabled = not (has_rules and cron_expression)
        else:
            button_disabled = not (has_rules and run_now_checked)


        # calling the workflow job
        if st.button("Submit", type="primary", disabled=button_disabled, use_container_width=True):
            with st.spinner("🚀 Processing Workflow Request..."):
                try:
                    full_table_name = f"{cat}.{schema}.{table}"
                    recipient_email = self.get_logged_in_user_email(self.config.get('EMAIL', 'address'))

                    if job_type == 'RUN NOW':
                        resp = self.wm.run_now_submit(
                            f"dqx_run_now_{table}",
                            self.config, 
                            full_table_name,
                            recipient_email
                        )
                        if resp.status_code in [200, 201]:
                            res_id = resp.json().get('run_id')
                            run_resp = self.wm.get_run_status(res_id)
                            page_url = run_resp.json().get('run_page_url')
                            msg = f"🚀 **Triggered Run:** {res_id}"
                            is_schedule_type = False
                        else:
                            st.error(f"Trigger run failed: {resp.text}")
                            return
                    
                    elif job_type == "SCHEDULE JOB":
                        resp_data = self.wm.create_scheduled_job(
                            f"dqx_schedule_{table}",
                            cron_expression,
                            timezone_id,
                            self.config,
                            full_table_name,
                            recipient_email
                        )
                        if resp_data.status_code in [200, 201]:
                            res_id = resp_data.json().get('job_id')
                            page_url = f"https://{self.wm.hostname}/#job/{res_id}"
                            msg = f"📅 **Created Scheduled Job ID:** {res_id}"
                            is_schedule_type = True
                        else:
                            st.error(f"Job schedule failed: {resp.text}")
                            return
                        
                    # send email and capture status
                    try:
                        run_status, recipient_email, email_msg = self.send_email(
                            self.config.get('EMAIL', 'address'), 
                            res_id, 
                            page_url, 
                            full_table_name,
                            dqx_mapped_df
                        )
                        email_status = f"✅ Email sent successfully to {recipient_email}!"
                    except Exception as email_error:
                        email_status = f"❌ Email notification failed to send. {email_error}"

                    # Save everything into session state
                    st.session_state.workflow_result = {
                        "id": res_id,
                        "url": page_url,
                        "email_msg": email_status,
                        "display_msg": msg,
                        "is_schedule": is_schedule_type
                    }
                except Exception as e:
                    st.error(f"Error: {str(e)}")
                
                if st.session_state.workflow_result:
                    res = st.session_state.workflow_result
                    st.success(res['display_msg'])
                    if res['url']:
                        label = "🔗 Open Databricks Job UI" if res['is_schedule'] else "🔗 Open Databricks Job Run"
                        st.link_button(label, res['url'])
                    st.info(res['email_msg'])
                    return 'submitted'


