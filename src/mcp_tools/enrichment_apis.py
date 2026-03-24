import json
import httpx
from langchain_core.documents import Document
from mcp_tools._utils import JSONFieldCompressor

from ._models import JobSubmitted
from ._jobs import registry as job_registry

def register_tools(mcp, app_config: dict) -> None:
    api_keys = app_config.get("api_keys", {})
    malware_bazaar_key = api_keys.get("malware_bazaar", "")
    abusedb_api_key = api_keys.get("abusedb", "")
    compression_model = app_config.get("compression_model")

    @mcp.tool(name="call_malware_bazaar_api")
    async def call_malware_bazaar_api(
        hash: str
    ) -> JobSubmitted:
        """
        Query MalwareBazaar for information about a file hash.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        hash:
            MD5, SHA1, or SHA256 hash of the file to look up.
        """
        async def _work():
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://mb-api.abuse.ch/api/v1/",
                    data={"query": "get_info", "hash": hash},
                    headers={"Auth-Key": malware_bazaar_key}
                )
            raw = response.json()

            if raw.get("query_status") != "ok":
                return {"status": "not_found", "hash": hash}

            doc = Document(page_content=json.dumps(raw, indent=2))
            compressor = JSONFieldCompressor(compression_model=compression_model)
            compressed = compressor.compress_documents(
                documents=[doc],
                query="MalwareBazaar hash lookup result. Summarise: verdict, malware family, key behaviours, vendor consensus. Drop redundant sandbox runs.",
            )

            return {"hash": hash, "result": compressed[0].page_content if compressed else "No results."}

        job_id = job_registry.submit("call_malware_bazaar_api", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="call_malware_bazaar_api", status="pending",
            message=f"MalwareBazaar lookup started. Poll get_job_status('{job_id}') to check progress.",
    )


    @mcp.tool(name="check_ip_abuseipdb")
    async def check_ip_abuseipdb(
        ip: str,
        max_age_in_days: int = 90,
    ) -> JobSubmitted:
        """
        Query AbuseIPDB for reputation information about an IP address.
        Returns immediately with a job_id. Poll get_job_status(job_id) to
        check progress and retrieve results when done.

        Parameters
        ----------
        ip:
            IPv4 or IPv6 address to look up.
        max_age_in_days:
            Only return reports from the last N days. Defaults to 90.
        """
        async def _work():
            api_key = os.environ.get("ABUSEIPDB_API_KEY")
            if not api_key:
                return {"error": "ABUSEIPDB_API_KEY environment variable not set."}

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.abuseipdb.com/api/v2/check",
                    headers={"Key": abusedb_api_key, "Accept": "application/json"},
                    params={"ipAddress": ip, "maxAgeInDays": max_age_in_days, "verbose": True},
                )
            raw = response.json()

            if "errors" in raw:
                return {"error": raw["errors"]}

            doc = Document(page_content=json.dumps(raw, indent=2))
            compressor = JSONFieldCompressor()
            compressed = compressor.compress_documents(
                documents=[doc],
                query="AbuseIPDB IP reputation result. Summarise: abuse confidence score, "
                    "total reports, country, ISP, usage type, and the most common reported "
                    "attack categories. Drop individual report details.",
            )

            return {"ip": ip, "result": compressed[0].page_content if compressed else "No results."}

        job_id = job_registry.submit("check_ip_abuseipdb", _work())
        return JobSubmitted(
            job_id=job_id, tool_name="check_ip_abuseipdb", status="pending",
            message=f"AbuseIPDB lookup started. Poll get_job_status('{job_id}') to check progress.",
        )