import streamlit as st
import json
import yaml
import pandas as pd
import time
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class EmailNotify:
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
        sender_email = 'dev.databricks26@gmail.com'
        sender_password = 'tqea avon drdx pgmn'
        
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


EmailNotify().send_success_email("databricks@databricks.com", "12345", "https://www.databricks.com", "test_table")
