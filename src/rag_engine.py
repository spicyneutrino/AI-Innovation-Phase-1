import os
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

class RAGEngine:
    def __init__(self, kb_id):
        self.kb_id = kb_id
        self.region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        self.client = boto3.client("bedrock-agent-runtime", region_name=self.region)

    def query(self, question):
        try:
            print(f"Asking Knowledge Base ({self.kb_id})...")
            model_arn = os.getenv(
                "BEDROCK_MODEL_ARN", 
                f"arn:aws:bedrock:{self.region}::foundation-model/amazon.nova-pro-v1:0"
            )
            
            response = self.client.retrieve_and_generate(
                input={'text': question},
                retrieveAndGenerateConfiguration={
                    'type': 'KNOWLEDGE_BASE',
                    'knowledgeBaseConfiguration': {
                        'knowledgeBaseId': self.kb_id,
                        'modelArn': model_arn,
                    }
                }
            )
            
            answer = response['output']['text']
            
            # Extract citations and metadata
            refs_out = []
            if 'citations' in response:
                for cit in response['citations']:
                    for ref in cit.get('retrievedReferences', []):
                        s3_uri = ref.get("location", {}).get("s3Location", {}).get("uri", "")
                        filename = s3_uri.split("/")[-1] if s3_uri else None
                        
                        # Extract metadata (Agency, Title, Law)
                        meta = ref.get("metadata", {}) or {}
                        
                        if filename:
                            refs_out.append({
                                "filename": filename,
                                "agency": meta.get("agency"),
                                "title": meta.get("title"),
                                "law": meta.get("law")
                            })

            # Deduplicate references
            seen = set()
            dedup = []
            for r in refs_out:
                # Create a unique key based on the file and its metadata
                key = (r.get("filename"), r.get("agency"), r.get("title"), r.get("law"))
                if key not in seen:
                    seen.add(key)
                    dedup.append(r)

            return answer, dedup

        except ClientError as e:
            print(f"Error: {e}")
            return "I encountered an error searching the regulations.", []