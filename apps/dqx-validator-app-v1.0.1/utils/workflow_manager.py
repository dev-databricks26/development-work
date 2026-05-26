import requests
import time
import copy

class WorkflowManager:
    def __init__(self, hostname, token, job_id, workflow_template):
        self.hostname = hostname
        self.token = token
        self.job_id = job_id
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.workflow_template = workflow_template


    def trigger_workflow_job(self, config, full_table_name, recipient_email):
        """Triggers a workflow and returns the run_id"""
        api_url = f"https://{self.hostname}/api/2.1/jobs/run-now"
        payload = {
            "job_id": self.job_id,
            "job_parameters": {
                "config_catalog_name": config.get('DEFAULT', 'dqx_config_catalog'),
                "config_schema_name": config.get('DEFAULT', 'dqx_config_schema'),
                "target_schema_name": f"dqx_{full_table_name.split('.')[1]}",
                "table_name": full_table_name,
                "email_sender":config.get('EMAIL', 'address'),
                "email_recipient": ','.join([recipient_email.strip()] + [e.strip() for e in config.get('EMAIL', 'copy_to').split(',') if e.strip()])
            }
        }
        response = requests.post(api_url, headers=self.headers, json=payload)
        response.raise_for_status()
        return response

    
    def get_run_status(self, run_id):
        """Returns 'RUNNING', 'SUCCESS', or 'FAILED'"""
        api_url = f"https://{self.hostname}/api/2.1/jobs/runs/get?run_id={run_id}"
        response = requests.get(api_url, headers=self.headers)
        response.raise_for_status()
        return response

    
    def run_now_submit(self, run_name, config, full_table_name, recipient_email):
        """Creates a deep copy of the template and injects configuration parameters."""
        api_url = f"https://{self.hostname}/api/2.1/jobs/runs/submit"
        
        # Deep copy to prevent mutating the original template across multiple runs
        payload = copy.deepcopy(self.workflow_template)

        # Inject top-level run name
        payload["run_name"] = run_name

        # Pull parameters dynamically
        shared_parameters = {
            "config_catalog_name": config.get('DEFAULT', 'dqx_config_catalog'),
            "config_schema_name": config.get('DEFAULT', 'dqx_config_schema'),
            "target_schema_name": f"dqx_{full_table_name.split('.')[1]}",
            "table_name": full_table_name,
            "email_sender": config.get('EMAIL', 'address'),
            "email_recipient": ','.join([recipient_email.strip()] + [e.strip() for e in config.get('EMAIL', 'copy_to').split(',') if e.strip()])
        }

        # Map parameters to every task defined in the template
        for task in payload.get("tasks", []):
            notebook_task = task.get("notebook_task", {})
            if notebook_task:  # Only update if notebook_task exists
                base_params = notebook_task.get("base_parameters", {})
                notebook_task["base_parameters"] = {**shared_parameters, **base_params}

        # Execute API call
        try:
            response = requests.post(api_url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            if response.status_code == 400:
                print(f"Databricks API Error Details: {response.text}")
            raise e


if __name__ == "__main__":
    manager = WorkflowManager("host", "token", "123","")
