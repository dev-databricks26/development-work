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


    def send_email(self, default_email, run_id, run_url, table_name):
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
            "Workspace": f"{self.config.get('DEFAULT', 'workspace_url')}",
            "Job": f"DQX_Run_Checks [{self.config.get('SQL', 'job_id')}]",
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
        status_color = "#2e7d32"
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
                    resp = self.wm.trigger_workflow(
                                self.config, 
                                f"{cat}.{schema}.{table}",
                                self.get_logged_in_user_email(self.config.get('EMAIL', 'address'))
                            )
                    if resp.status_code == 200:
                        run_id = resp.json().get('run_id')
                        run_resp = self.wm.get_run_status(run_id)
                        run_page_url = run_resp.json().get('run_page_url')
                        
                        # send email and capture status
                        try:
                            run_status, recipient_email, email_msg = self.send_email(
                                self.config.get('EMAIL', 'address'), 
                                run_id, 
                                run_page_url, 
                                f"{cat}.{schema}.{table}"
                            )
                            email_status = f"✅ Email sent successfully to {recipient_email}!"
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
#     send_email('dev.databricks26@gmail.com', 'test_run_id', 'test_run_page_url', 'test_table')
