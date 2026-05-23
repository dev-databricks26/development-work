import streamlit as st
import json
import yaml
import pandas as pd
import time
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class UISubmitComponents:
    def __init__(self, db_manager, dqx_h , workflow_manager, config_catalog, config):
        self.db = db_manager
        self.wm = workflow_manager
        self.dqx = dqx_h
        self.config = config
        self.config_catalog = self.config.get('DEFAULT', 'dqx_catalog_name')
        self.config_schema = self.config.get('DEFAULT', 'dqx_config_schema')
    
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

    def send_success_email(self, recipient_email, run_id, run_url, table_name):
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        sender_email = self.config.get('EMAIL', 'address')
        sender_password = self.config.get('EMAIL', 'password')
        
        # Capture the original fallback email for CC
        cc_email = recipient_email

        # Automatically identify the logged-in user
        recipient_email = self.get_logged_in_user_email(cc_email)
        print("recipient_email ==> ", recipient_email)

        subject = f"🚀 DQX Workflow Triggered: {table_name}"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h3 style="color: #2e7d32;">DQX Execution Started</h3>
            <p>A Data Quality workflow has been successfully triggered for the table: <b>{table_name}</b>.</p>
            <hr>
            <p><b>Run Details:</b></p>
            <ul>
            <li><b>Run ID:</b> {run_id}</li>
            <li><b>Status:</b> Triggered</li>
            </ul>
            <p><a href="{run_url}" style="display: inline-block; padding: 10px 20px; background-color: #007bff; color: white; text-decoration: none; border-radius: 5px;">View Databricks Run</a></p>
            <p style="font-size: 0.8em; color: #666;">This is an automated notification from the DQX UI.</p>
        </body>
        </html>
        """

        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Cc'] = cc_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        # Combine recipients into a unique list of strings for SMTP transmission
        to_addrs = list(set(filter(None, [recipient_email, cc_email])))

        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg, to_addrs=to_addrs)
            return True, "Email sent successfully"
        except Exception as e:
            st.error(f"Failed to send email: {e}")
            return False, str(e)

    def render_submit(self, cat, schema, table):
        st.divider()
        st.subheader("🏁 Final Review & Execution")

        # 1. Initialize variables to ensure they exist even if DB call fails
        rules_list = []
        has_rules = False

        # Fetch current mappings from DB
        dqx_mapped_df = self.db.fetch_dqx_mappings(self.config_catalog, self.config_schema, cat, schema, table)
        st.dataframe(dqx_mapped_df[["column", "rule_name", "rule_function", "criticality", "arguments"]])

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

        # 2. Export Section
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

        # 3. Execution Section
        st.subheader("🚀 Execution")
        # 1. Initialize session state to hold workflow results
        if 'workflow_result' not in st.session_state:
            st.session_state.workflow_result = None

        if st.button("Apply/Run DQ Rules", type="primary", disabled=not has_rules, use_container_width=True):
            with st.spinner("🚀 Running Workflow to Apply Rules..."):
                try:
                    resp = self.wm.trigger_workflow(self.config_catalog, cat, self.config_schema, schema, table)
                    if resp.status_code == 200:
                        run_id = resp.json().get('run_id')
                        run_resp = self.wm.get_run_status(run_id)
                        run_page_url = run_resp.json().get('run_page_url')
                        
                        # send email and capture status
                        try:
                            self.send_success_email('dev.databricks26@gmail.com', run_id, run_page_url, f"{cat}.{schema}.{table}")
                            email_status = "✅ Email sent successfully!"
                        except Exception:
                            email_status = "❌ Email notification failed to send."

                        # 2. Save everything into session state
                        st.session_state.workflow_result = {
                            "run_id": run_id,
                            "url": run_page_url,
                            "email_msg": email_status
                        }
                    else:
                        st.error(f"Trigger failed: {resp.text}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")

        if st.session_state.workflow_result:
            res = st.session_state.workflow_result
            st.success(f"🚀 **Triggered Workflow:** {res['run_id']}")
            if res['url']:
                st.link_button("🔗 Open Databricks Job Run", res['url'])
            st.info(res['email_msg'])
            return 'submitted'


# if __name__ == "__main__":
#     UISubmitComponents()
#     send_success_email('dev.databricks26@gmail.com', 'test_run_id', 'test_run_page_url', 'test_table')
