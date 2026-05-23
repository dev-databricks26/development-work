from databricks.sdk import WorkspaceClient
from databricks.labs.dqx.profiler.profiler import DQProfiler
from databricks.labs.dqx.config import LLMModelConfig,InputConfig
from databricks.labs.dqx.profiler.generator import DQGenerator
import streamlit as st
import os
import json
from datetime import date, datetime
import time
import pandas as pd


class dqx_handler:
    def __init__(self, spark_session):
        self.spark = spark_session
        self.ws = WorkspaceClient()
        self.llm_cfg = LLMModelConfig("databricks/databricks-meta-llama-3-3-70b-instruct")
        self.profiler = DQProfiler(workspace_client=self.ws, llm_model_config=self.llm_cfg)
        self.generator = DQGenerator(self.ws, llm_model_config=self.llm_cfg)
        self.profile_data_path = os.path.join(os.getcwd(), "profile_data")
        os.makedirs(self.profile_data_path, exist_ok=True)
    

    @staticmethod
    def json_serial(obj):
        """Static method to handle date/datetime serialization in JSON."""
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        # If the object has a __dict__, try to serialize that (for DQX objects)
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        raise TypeError(f"Type {type(obj)} not serializable")


    def save_profile_data(self, input_table_name, columns_list=None, sample_percent=None):
        # Profile the table and save the results
        run_date = datetime.now().strftime("%Y%m%d")
        if columns_list is None or not columns_list:
            raise ValueError("columns_list must be provided and non-empty.")
        
        df = self.spark.read.table(input_table_name)
        # sampling logic
        if sample_percent is not None:
            if not (0 < sample_percent <= 100):
                raise ValueError("sample_percent must be between 0 and 100.")
            # Spark sample uses a fraction (0.0 to 1.0)
            df = df.sample(withReplacement=False, fraction=sample_percent / 100.0)

        # creating summary profile
        summary_stats, profiles = self.profiler.profile(
            df=df,
            columns=columns_list
        )

        table_dir = os.path.join(self.profile_data_path, input_table_name.replace('.', '_'))
        os.makedirs(table_dir, exist_ok=True)  # Ensure directory exists
        file_path = os.path.join(table_dir, "profile.json")
        with open(file_path, "w") as f:
            json.dump({"summary_stats": summary_stats, "profiles": profiles, "run_date": run_date}, f , default=self.json_serial)
        return file_path


    @st.cache_data(ttl=1200, show_spinner=False)
    def load_profile_data(_self, input_table_name, columns_list=None, sample_percent=None):
        table_dir = os.path.join(_self.profile_data_path, input_table_name.replace('.', '_'))
        file_path = os.path.join(table_dir, "profile.json")
        
        if not os.path.exists(file_path):
            _self.save_profile_data(input_table_name, columns_list, sample_percent)
        
        time.sleep(5)
        with open(file_path, "r") as f:
            data = json.load(f)
        summary_stats = data.get("summary_stats")
        profiles = data.get("profiles")
        if columns_list:
            summary_stats = {col: summary_stats.get(col) for col in columns_list if col in summary_stats}
            profiles = [profile for profile in profiles if profile["column"] in columns_list]
        return summary_stats, profiles


    @st.cache_data(ttl=1200, show_spinner='Generating rules...')
    def generate_profile_checks(_self, profiles, input_table_name):
        # Convert dict profiles to objects with attribute access if needed
        from types import SimpleNamespace
        profile_objs = [SimpleNamespace(**profile) if isinstance(profile, dict) else profile for profile in profiles]
        return _self.generator.generate_dq_rules(profile_objs)
    
    
    @st.cache_data(ttl=1200, show_spinner=False)
    def ai_assisted_rule_generation(_self, user_prompt, input_table_name):
        return _self.generator.generate_dq_rules_ai_assisted(
            user_input=user_prompt,
            input_config=InputConfig(location=input_table_name)
        )

    @st.cache_data(ttl=1200, show_spinner=False)
    def ai_detect_primary_key(_self, input_table_name):
        return _self.profiler.detect_primary_keys_with_llm(
            input_config=InputConfig(location=input_table_name)
        )


if __name__ == "__main__":
    handler = dqx_handler(spark)
    print(handler.ws.config.host)
    print(handler.ws.config.token)
    tbl = 'dqx_sandbox.dqx_bronze.product'
    inp = """
    Phone numbers should follow standard format.
    customer_email is valid.
    customer_state is a string with less than 5 letter.
    """
    # handler.save_profile_data(tbl, handler.spark.read.table(tbl).columns, 99)
    res_summary_stats, res_profiles = handler.load_profile_data(tbl, handler.spark.read.table(tbl).columns, 99)
    checks = handler.generate_profile_checks(res_profiles,tbl)
    print(res_summary_stats,'\n',res_profiles)
    print(checks)
    
