import os
import sys

# Ensure runtime dir is set for the crawler (Lambda writable filesystem).
os.environ.setdefault("SOS_CRAWLER_RUNTIME_DIR", "/tmp/sos_crawler")

# Add src to the *front* of sys.path so it takes precedence over any installed package.
sys.path.insert(0, os.path.join(os.getcwd(), "src"))

from sos_crawler.orchestrator import run_spiders  # noqa: E402

def handler(event, context):
    state = event.get("state", "MS")
    print(f"Starting crawl for state: {state}")
    run_spiders(states=[state])
    return {"statusCode": 200, "body": f"Crawl completed for {state}"}



# import sys
# import os

# # Ensure the src directory is in the path
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# from sos_crawler.orchestrator import run_spiders


# def handler(event, context):
#     # event can be {"state": "AL"} or {"state": "ALL"}
#     target_state = event.get("state", "ALL")
    
#     # 1. Execute the Crawler
#     # Ensure run_spiders is configured to save to the correct S3-mapped paths
#     run_spiders(states=[target_state] if target_state != "ALL" else None)
    
#     # 2. Trigger the Bedrock Sync
#     # Get IDs from environment variables you'll set in the Lambda Console
#     kb_id = os.environ.get("BEDROCK_KB_ID")
#     ds_id = os.environ.get("BEDROCK_DS_ID")
    
#     if kb_id and ds_id:
#         client = boto3.client('bedrock-agent')
#         client.start_ingestion_job(
#             knowledgeBaseId=kb_id,
#             dataSourceId=ds_id
#         )
    
#     return {"status": "success", "state": target_state}