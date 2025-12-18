import os
import boto3
import re
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

class RAGEngine:
    def __init__(self, kb_id):
        self.kb_id = kb_id
        self.region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        # Client for the Knowledge Base
        self.client = boto3.client("bedrock-agent-runtime", region_name=self.region)

    def query(self, question):
        try:
            print(f"Asking Knowledge Base ({self.kb_id})...")

            model_arn = os.getenv(
                "BEDROCK_MODEL_ARN", 
                f"arn:aws:bedrock:{self.region}::foundation-model/amazon.nova-pro-v1:0"
            )
            
            # This API call connects the KB + The Model
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
            
            raw_answer = response['output']['text']

            clean_answer = re.sub(r'\[\d+\]|%\[\d+\]%|\{[^}]+\}', '', raw_answer).strip()

            citations = []
            if 'citations' in response:
                for cit in response['citations']:
                    for ref in cit.get('retrievedReferences', []):
                        uri = ref.get('location', {}).get('s3Location', {}).get('uri', '')
                        if uri: citations.append(uri.split('/')[-1])
            
            return clean_answer, list(set(citations))

        except ClientError as e:
            return f"Error: {e}", []