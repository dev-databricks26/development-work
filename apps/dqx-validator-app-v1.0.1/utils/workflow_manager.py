import requests
import time

class WorkflowManager:
    def __init__(self, hostname, token, job_id):
        self.hostname = hostname
        self.token = token
        self.job_id = job_id
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def trigger_workflow(self, config, full_table_name, receipient_email):
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
                "email_recipient": ','.join([receipient_email.strip()] + [e.strip() for e in config.get('EMAIL', 'copy_to').split(',') if e.strip()])
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


if __name__ == "__main__":
    manager = WorkflowManager("host", "token", "123")
    run_id = manager.trigger_workflow(...)
    status = manager.get_run_status(run_id)
