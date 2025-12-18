# inside query()

answer = response["output"]["text"]
refs_out = []

for cit in response.get("citations", []):
    for ref in cit.get("retrievedReferences", []):
        s3_uri = ref.get("location", {}).get("s3Location", {}).get("uri", "")
        filename = s3_uri.split("/")[-1] if s3_uri else None

        meta = ref.get("metadata", {}) or {}
        refs_out.append({
            "filename": filename,
            "uri": s3_uri,
            "agency": meta.get("agency"),
            "title": meta.get("title"),
            "law": meta.get("law"),
        })

# de-dup by filename+fields
seen = set()
dedup = []
for r in refs_out:
    key = (r.get("filename"), r.get("agency"), r.get("title"), r.get("law"))
    if key not in seen:
        seen.add(key)
        dedup.append(r)

return answer, dedup
