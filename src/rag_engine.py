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

    def query(
        self,
        question: str,
        session_id: str | None = None,
        target_states: list[str] | None = None,
    ) -> tuple[str, list, str | None]:
        try:
            print(f"Asking Knowledge Base ({self.kb_id})...")
            model_arn = os.getenv(
                "BEDROCK_MODEL_ARN",
                f"arn:aws:bedrock:{self.region}::foundation-model/amazon.nova-pro-v1:0",
            )

            kb_configuration: dict = {
                "knowledgeBaseId": self.kb_id,
                "modelArn": model_arn,
            }

            system_instruction = (
                "You are an expert regulatory intelligence assistant for the Mississippi Secretary of State. "
                "Your job is to provide clear, professional, and highly accurate answers regarding state regulations. "
                "Read the Search Results carefully. You are encouraged to synthesize partial information. "
                "If asked to compare states, create a structured side-by-side comparison using the data available. "
                "If a specific detail is missing for one state but present for another, explain exactly what you found "
                "and clearly state which specific details are missing from the current database. "
                "Always format your response with clean spacing and bullet points.\n\n"
                "Search Results:\n$search_results$\n\n"
                "$output_format_instructions$\n\n"
                "User Query:\n$query$"
            )

            kb_configuration["generationConfiguration"] = {
                "promptTemplate": {
                    "textPromptTemplate": system_instruction,
                },
            }

            combined_states = [
                s.strip().upper()
                for s in (target_states or [])
                if isinstance(s, str) and s.strip()
            ]

            retrieval_config = {
                "vectorSearchConfiguration": {
                    "numberOfResults": 20,
                },
            }
            if combined_states:
                retrieval_config["vectorSearchConfiguration"]["filter"] = {
                    "in": {
                        "key": "state",
                        "value": combined_states,
                    },
                }
                kb_configuration["retrievalConfiguration"] = retrieval_config

            params = {
                "input": {"text": question},
                "retrieveAndGenerateConfiguration": {
                    "type": "KNOWLEDGE_BASE",
                    "knowledgeBaseConfiguration": kb_configuration,
                },
            }
            if session_id:
                params["sessionId"] = session_id

            response = self.client.retrieve_and_generate(**params)

            # Bedrock creates the session on the first call and returns its ID.
            # Capture it so the caller can pass it back on subsequent turns.
            returned_session_id = response.get("sessionId")

            answer = response["output"]["text"]

            # Extract citations and metadata
            refs_out = []
            if "citations" in response:
                for cit in response["citations"]:
                    for ref in cit.get("retrievedReferences", []):
                        s3_uri = ref.get("location", {}).get("s3Location", {}).get("uri", "")
                        filename = s3_uri.split("/")[-1] if s3_uri else None

                        meta = ref.get("metadata", {}) or {}

                        if filename:
                            refs_out.append({
                                "s3_uri": s3_uri,
                                "filename": filename,
                                "agency": meta.get("agency"),
                                "title": meta.get("title"),
                                "law": meta.get("law"),
                                "state": meta.get("state"),
                                "source_url": meta.get("source_url") or meta.get("doc_url"),
                            })

            # Deduplicate
            seen = set()
            dedup = []
            for r in refs_out:
                key = (r.get("filename"), r.get("agency"), r.get("title"), r.get("law"))
                if key not in seen:
                    seen.add(key)
                    dedup.append(r)

            return answer, dedup, returned_session_id

        except ClientError as e:
            print(f"Error: {e}")
            return "I encountered an error searching the regulations.", [], None

    def get_presigned_url(self, s3_uri: str, expiry: int = 3600) -> str | None:
        """Generate a presigned GET URL for an S3 object. Returns None on error."""
        if not s3_uri or not s3_uri.startswith("s3://"):
            return None
        without_scheme = s3_uri[5:]
        bucket, _, key = without_scheme.partition("/")
        try:
            s3 = boto3.client("s3", region_name=self.region)
            return s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expiry,
            )
        except ClientError:
            return None

    def get_document_text(self, s3_uri: str, max_chars: int = 3000) -> str | None:
        """Fetch the first max_chars characters of a text document from S3."""
        if not s3_uri or not s3_uri.startswith("s3://"):
            return None
        without_scheme = s3_uri[5:]
        bucket, _, key = without_scheme.partition("/")
        try:
            s3 = boto3.client("s3", region_name=self.region)
            obj = s3.get_object(Bucket=bucket, Key=key)
            raw = obj["Body"].read(max_chars + 1)
            text = raw.decode("utf-8", errors="replace")
            return text[:max_chars] + ("\u2026" if len(text) > max_chars else "")
        except ClientError:
            return None
