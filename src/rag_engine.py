import boto3
from botocore.exceptions import ClientError

class RAGEngine:
    def __init__(self, kb_id):
        self.kb_id = kb_id
        # Client for the Knowledge Base
        self.client = boto3.client("bedrock-agent-runtime", region_name="us-east-1")

    def query(self, question):
        try:
            print(f"Asking Knowledge Base ({self.kb_id})...")
            
            # This API call connects the KB + The Model
            response = self.client.retrieve_and_generate(
                input={'text': question},
                retrieveAndGenerateConfiguration={
                    'type': 'KNOWLEDGE_BASE',
                    'knowledgeBaseConfiguration': {
                        'knowledgeBaseId': self.kb_id,
                        'modelArn': 'arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0',
                    }
                }
            )
            
            # Extract Answer & Citations
            answer = response['output']['text']
            citations = []
            if 'citations' in response:
                for cit in response['citations']:
                    for ref in cit.get('retrievedReferences', []):
                        uri = ref.get('location', {}).get('s3Location', {}).get('uri', '')
                        if uri: citations.append(uri.split('/')[-1])
            
            return answer, list(set(citations))

        except ClientError as e:
            return f"Error: {e}", []