import os
import boto3
import re
from botocore.exceptions import ClientError
import streamlit as st

class RAGEngine:
    def __init__(self, kb_id):
        self.kb_id = kb_id
        # Use the region from secrets, or default to us-east-1
        self.region = st.secrets.get("AWS_REGION", "us-east-1")

        # Initialize the Bedrock client with the secrets
        self.client = boto3.client(
            "bedrock-agent-runtime",
            region_name=self.region,
            aws_access_key_id=st.secrets["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=st.secrets["AWS_SECRET_ACCESS_KEY"]
        )

    def query(self, question):
        try:
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
            
            raw_answer = response['output']['text']
            
            # Clean up citations markers like [1], %[1]%, etc.
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